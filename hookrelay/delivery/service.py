import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from hookrelay.core.config import get_settings
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
) -> DeliveryAttempt:
    settings = get_settings()
    started_at = datetime.now(UTC)
    started_clock = time.perf_counter()
    response_status: int | None = None
    response_body_preview: str | None = None
    error_type: str | None = None
    error_message: str | None = None

    body = {
        "id": str(event.id),
        "type": event.event_type,
        "created_at": event.created_at.isoformat(),
        "data": event.payload,
    }

    try:
        response = await client.post(endpoint.url, json=body)
        response_status = response.status_code
        preview = response.content[: settings.response_body_preview_bytes]
        response_body_preview = preview.decode("utf-8", errors="replace")
        delivery.status = (
            DeliveryStatus.DELIVERED.value
            if 200 <= response.status_code < 300
            else DeliveryStatus.FAILED.value
        )
    except httpx.HTTPError as exc:
        delivery.status = DeliveryStatus.FAILED.value
        error_type = type(exc).__name__[:100]
        error_message = str(exc)[:500]

    completed_at = datetime.now(UTC)
    latency_ms = max(0, round((time.perf_counter() - started_clock) * 1000))
    delivery.attempt_count += 1
    if delivery.status == DeliveryStatus.DELIVERED.value:
        delivery.delivered_at = completed_at

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
