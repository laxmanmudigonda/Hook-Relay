import json
import uuid
from datetime import UTC, datetime

import httpx

from hookrelay.delivery.retry import RetryPolicy
from hookrelay.delivery.service import attempt_delivery
from hookrelay.delivery.signing import verify_webhook_signature
from hookrelay.models import Delivery, DeliveryStatus, Event, WebhookEndpoint


class RecordingSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    def add(self, item: object) -> None:
        self.added.append(item)

    async def commit(self) -> None:
        self.commits += 1


def delivery_objects(url: str) -> tuple[Delivery, Event, WebhookEndpoint]:
    event = Event(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        event_type="payment.completed",
        payload={"payment_id": "pay_123"},
        created_at=datetime.now(UTC),
    )
    endpoint = WebhookEndpoint(
        id=uuid.uuid4(),
        tenant_id=event.tenant_id,
        url=url,
        signing_secret="test-signing-secret-with-at-least-32-bytes",
        enabled=True,
    )
    delivery = Delivery(
        id=uuid.uuid4(),
        event_id=event.id,
        endpoint_id=endpoint.id,
        status=DeliveryStatus.PENDING.value,
        attempt_count=0,
        current_attempt_count=0,
        replay_count=0,
    )
    return delivery, event, endpoint


terminal_policy = RetryPolicy(
    max_attempts=1,
    base_delay_seconds=1,
    max_delay_seconds=60,
)


async def test_successful_delivery_records_attempt_and_stable_envelope() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        assert verify_webhook_signature(endpoint.signing_secret, request.headers, request.content)
        assert request.headers["X-HookRelay-Event-ID"] == str(event.id)
        return httpx.Response(200, json={"accepted": True})

    session = RecordingSession()
    delivery, event, endpoint = delivery_objects("https://receiver.example/webhook")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        attempt = await attempt_delivery(
            session,
            client,
            delivery,
            event,
            endpoint,
            terminal_policy,  # type: ignore[arg-type]
        )

    assert captured["id"] == str(event.id)
    assert captured["type"] == "payment.completed"
    assert captured["data"] == {"payment_id": "pay_123"}
    assert delivery.status == DeliveryStatus.DELIVERED.value
    assert delivery.attempt_count == 1
    assert delivery.delivered_at is not None
    assert attempt.response_status == 200
    assert attempt.error_type is None
    assert session.commits == 1


async def test_http_500_exhaustion_dead_letters_delivery() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="receiver failed")

    session = RecordingSession()
    delivery, event, endpoint = delivery_objects("https://receiver.example/fail")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        attempt = await attempt_delivery(
            session,
            client,
            delivery,
            event,
            endpoint,
            terminal_policy,  # type: ignore[arg-type]
        )

    assert delivery.status == DeliveryStatus.DEAD_LETTERED.value
    assert delivery.delivered_at is None
    assert attempt.response_status == 500
    assert attempt.response_body_preview == "receiver failed"


async def test_transport_error_exhaustion_dead_letters_delivery() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    session = RecordingSession()
    delivery, event, endpoint = delivery_objects("https://receiver.example/unavailable")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        attempt = await attempt_delivery(
            session,
            client,
            delivery,
            event,
            endpoint,
            terminal_policy,  # type: ignore[arg-type]
        )

    assert delivery.status == DeliveryStatus.DEAD_LETTERED.value
    assert attempt.response_status is None
    assert attempt.error_type == "ConnectError"
    assert attempt.error_message == "connection refused"


async def test_retryable_failure_schedules_next_attempt() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "3"})

    session = RecordingSession()
    delivery, event, endpoint = delivery_objects("https://receiver.example/rate-limited")
    policy = RetryPolicy(max_attempts=3, base_delay_seconds=1, max_delay_seconds=10)
    before = datetime.now(UTC)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        attempt = await attempt_delivery(
            session,
            client,
            delivery,
            event,
            endpoint,
            policy,  # type: ignore[arg-type]
        )

    assert delivery.status == DeliveryStatus.RETRY_SCHEDULED.value
    assert delivery.current_attempt_count == 1
    assert delivery.next_attempt_at is not None
    assert (delivery.next_attempt_at - before).total_seconds() >= 3
    assert attempt.response_status == 429


async def test_non_retryable_failure_is_failed_not_dead_lettered() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="invalid request")

    session = RecordingSession()
    delivery, event, endpoint = delivery_objects("https://receiver.example/bad-request")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        attempt = await attempt_delivery(
            session,
            client,
            delivery,
            event,
            endpoint,
            terminal_policy,  # type: ignore[arg-type]
        )

    assert delivery.status == DeliveryStatus.FAILED.value
    assert delivery.current_attempt_count == 1
    assert attempt.response_status == 400


async def test_success_after_replay_preserves_lifetime_attempt_number() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    session = RecordingSession()
    delivery, event, endpoint = delivery_objects("https://receiver.example/recovered")
    delivery.attempt_count = 5
    delivery.current_attempt_count = 0
    delivery.replay_count = 1
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        attempt = await attempt_delivery(
            session,
            client,
            delivery,
            event,
            endpoint,
            terminal_policy,  # type: ignore[arg-type]
        )

    assert delivery.status == DeliveryStatus.DELIVERED.value
    assert delivery.attempt_count == 6
    assert delivery.current_attempt_count == 1
    assert attempt.attempt_number == 6
