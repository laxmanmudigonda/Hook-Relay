import json
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from hookrelay.core.config import get_settings
from hookrelay.delivery.retry import RetryPolicy, parse_retry_after
from hookrelay.delivery.signing import build_signature_headers
from hookrelay.models import Delivery, DeliveryAttempt, DeliveryStatus, Event, WebhookEndpoint


async def get_http_client() -> AsyncIterator[httpx.AsyncClient]:
    settings = get_settings()
    async with httpx.AsyncClient(
        timeout=settings.delivery_timeout_seconds,
        follow_redirects=False,
    ) as client:
        yield client


async def attempt_delivery(
    session: AsyncSession,
    client: httpx.AsyncClient,
    delivery: Delivery,
    event: Event,
    endpoint: WebhookEndpoint,
    retry_policy: RetryPolicy | None = None,
) -> DeliveryAttempt:
    settings = get_settings()
    policy = retry_policy or RetryPolicy(
        max_attempts=settings.max_delivery_attempts,
        base_delay_seconds=settings.retry_base_delay_seconds,
        max_delay_seconds=settings.retry_max_delay_seconds,
    )
    started_at = datetime.now(UTC)
    started_clock = time.perf_counter()
    response_status: int | None = None
    response_body_preview: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    retry_after_seconds: float | None = None
    transport_error = False

    envelope = {
        "id": str(event.id),
        "type": event.event_type,
        "created_at": event.created_at.isoformat(),
        "data": event.payload,
    }
    body = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    headers = build_signature_headers(endpoint.signing_secret, str(event.id), body)

    try:
        response = await client.post(endpoint.url, content=body, headers=headers)
        response_status = response.status_code
        preview = response.content[: settings.response_body_preview_bytes]
        response_body_preview = preview.decode("utf-8", errors="replace")
        retry_after_seconds = parse_retry_after(response.headers.get("Retry-After"))
    except httpx.HTTPError as exc:
        transport_error = True
        error_type = type(exc).__name__[:100]
        error_message = str(exc)[:500]

    completed_at = datetime.now(UTC)
    latency_ms = max(0, round((time.perf_counter() - started_clock) * 1000))
    delivery.attempt_count += 1
    delivery.current_attempt_count += 1
    delivery.processing_started_at = None
    if response_status is not None and 200 <= response_status < 300:
        delivery.status = DeliveryStatus.DELIVERED.value
        delivery.delivered_at = completed_at
        delivery.next_attempt_at = None
    else:
        decision = policy.decide(
            attempt_number=delivery.current_attempt_count,
            response_status=response_status,
            transport_error=transport_error,
            retry_after_seconds=retry_after_seconds,
        )
        if decision.should_retry and decision.delay_seconds is not None:
            delivery.status = DeliveryStatus.RETRY_SCHEDULED.value
            delivery.next_attempt_at = completed_at + timedelta(seconds=decision.delay_seconds)
        else:
            delivery.status = (
                DeliveryStatus.DEAD_LETTERED.value
                if decision.reason == "attempts_exhausted"
                else DeliveryStatus.FAILED.value
            )
            delivery.next_attempt_at = None

    attempt = DeliveryAttempt(
        id=uuid.uuid4(),
        delivery_id=delivery.id,
        attempt_number=delivery.attempt_count,
        started_at=started_at,
        completed_at=completed_at,
        response_status=response_status,
        response_body_preview=response_body_preview,
        error_type=error_type,
        error_message=error_message,
        latency_ms=latency_ms,
    )
    session.add(attempt)
    await session.commit()
    return attempt
