import uuid

import pytest
from fastapi import HTTPException
from redis.exceptions import ConnectionError as RedisConnectionError

from hookrelay.api.routes import events
from hookrelay.models import Delivery, DeliveryStatus


def pending_delivery() -> Delivery:
    return Delivery(
        id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        endpoint_id=uuid.uuid4(),
        status=DeliveryStatus.PENDING.value,
        attempt_count=0,
    )


async def test_queue_failure_reports_persisted_event(monkeypatch: pytest.MonkeyPatch) -> None:
    delivery = pending_delivery()
    event_id = delivery.event_id

    async def fail_publish(_delivery_id: uuid.UUID) -> None:
        raise RedisConnectionError("redis unavailable")

    monkeypatch.setattr(events, "publish_delivery", fail_publish)

    with pytest.raises(HTTPException) as raised:
        await events.publish_pending_deliveries([delivery], event_id)

    assert raised.value.status_code == 503
    assert raised.value.detail == {
        "message": "event persisted but delivery queue is unavailable",
        "event_id": str(event_id),
    }


async def test_terminal_delivery_is_not_republished(monkeypatch: pytest.MonkeyPatch) -> None:
    delivery = pending_delivery()
    delivery.status = DeliveryStatus.DELIVERED.value
    published: list[uuid.UUID] = []

    async def record_publish(delivery_id: uuid.UUID) -> None:
        published.append(delivery_id)

    monkeypatch.setattr(events, "publish_delivery", record_publish)

    await events.publish_pending_deliveries([delivery], delivery.event_id)

    assert published == []


async def test_retry_scheduled_delivery_can_be_republished_for_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivery = pending_delivery()
    delivery.status = DeliveryStatus.RETRY_SCHEDULED.value
    published: list[uuid.UUID] = []

    async def record_publish(delivery_id: uuid.UUID) -> None:
        published.append(delivery_id)

    monkeypatch.setattr(events, "publish_delivery", record_publish)

    await events.publish_pending_deliveries([delivery], delivery.event_id)

    assert published == [delivery.id]
