import uuid
from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from hookrelay.models import Delivery, OutboxEvent


def add_delivery_outbox(session: AsyncSession, deliveries: Iterable[Delivery]) -> None:
    session.add_all(
        [
            OutboxEvent(
                id=uuid.uuid4(),
                aggregate_type="delivery",
                aggregate_id=delivery.id,
                event_type="delivery.requested",
                payload={"delivery_id": str(delivery.id)},
            )
            for delivery in deliveries
        ]
    )
