import uuid

from hookrelay.api.routes.events import enqueue_incomplete_deliveries
from hookrelay.models import Delivery, DeliveryStatus, OutboxEvent


class RecordingSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add_all(self, items: list[object]) -> None:
        self.added.extend(items)


def delivery(status: DeliveryStatus) -> Delivery:
    return Delivery(
        id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        endpoint_id=uuid.uuid4(),
        status=status.value,
        attempt_count=0,
        current_attempt_count=0,
        replay_count=0,
    )


def test_pending_and_retry_scheduled_deliveries_create_outbox_rows() -> None:
    session = RecordingSession()
    pending = delivery(DeliveryStatus.PENDING)
    retry = delivery(DeliveryStatus.RETRY_SCHEDULED)

    enqueue_incomplete_deliveries(session, [pending, retry])  # type: ignore[arg-type]

    rows = [item for item in session.added if isinstance(item, OutboxEvent)]
    assert len(rows) == 2
    assert {item.aggregate_id for item in rows} == {pending.id, retry.id}


def test_terminal_deliveries_do_not_create_outbox_rows() -> None:
    session = RecordingSession()

    enqueue_incomplete_deliveries(
        session,  # type: ignore[arg-type]
        [delivery(DeliveryStatus.DELIVERED), delivery(DeliveryStatus.DEAD_LETTERED)],
    )

    assert session.added == []
