import json
import uuid
from datetime import UTC, datetime

import httpx

from hookrelay.delivery.service import attempt_delivery
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
        enabled=True,
    )
    delivery = Delivery(
        id=uuid.uuid4(),
        event_id=event.id,
        endpoint_id=endpoint.id,
        status=DeliveryStatus.PENDING.value,
        attempt_count=0,
    )
    return delivery, event, endpoint


async def test_successful_delivery_records_attempt_and_stable_envelope() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"accepted": True})

    session = RecordingSession()
    delivery, event, endpoint = delivery_objects("https://receiver.example/webhook")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        attempt = await attempt_delivery(session, client, delivery, event, endpoint)  # type: ignore[arg-type]

    assert captured["id"] == str(event.id)
    assert captured["type"] == "payment.completed"
    assert captured["data"] == {"payment_id": "pay_123"}
    assert delivery.status == DeliveryStatus.DELIVERED.value
    assert delivery.attempt_count == 1
    assert delivery.delivered_at is not None
    assert attempt.response_status == 200
    assert attempt.error_type is None
    assert session.commits == 1


async def test_http_500_records_failed_delivery() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="receiver failed")

    session = RecordingSession()
    delivery, event, endpoint = delivery_objects("https://receiver.example/fail")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        attempt = await attempt_delivery(session, client, delivery, event, endpoint)  # type: ignore[arg-type]

    assert delivery.status == DeliveryStatus.FAILED.value
    assert delivery.delivered_at is None
    assert attempt.response_status == 500
    assert attempt.response_body_preview == "receiver failed"


async def test_transport_error_records_error_without_response_status() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    session = RecordingSession()
    delivery, event, endpoint = delivery_objects("https://receiver.example/unavailable")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        attempt = await attempt_delivery(session, client, delivery, event, endpoint)  # type: ignore[arg-type]

    assert delivery.status == DeliveryStatus.FAILED.value
    assert attempt.response_status is None
    assert attempt.error_type == "ConnectError"
    assert attempt.error_message == "connection refused"
