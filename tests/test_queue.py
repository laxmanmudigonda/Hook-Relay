import uuid
from datetime import UTC, datetime

from hookrelay.queue.redis import promote_due_retries, publish_delivery, schedule_retry


class RecordingRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.zadd_calls: list[tuple[str, dict[str, float]]] = []
        self.eval_calls: list[tuple[object, ...]] = []

    async def xadd(self, stream: str, fields: dict[str, str]) -> str:
        self.calls.append((stream, fields))
        return "1-0"

    async def zadd(self, name: str, mapping: dict[str, float]) -> int:
        self.zadd_calls.append((name, mapping))
        return 1

    async def eval(self, *args: object) -> list[str]:
        self.eval_calls.append(args)
        return ["delivery-1"]


async def test_publish_delivery_uses_stable_identifier() -> None:
    redis = RecordingRedis()
    delivery_id = uuid.uuid4()

    message_id = await publish_delivery(delivery_id, redis)  # type: ignore[arg-type]

    assert message_id == "1-0"
    assert redis.calls == [("hookrelay:deliveries", {"delivery_id": str(delivery_id)})]


async def test_schedule_retry_uses_timestamp_score() -> None:
    redis = RecordingRedis()
    delivery_id = uuid.uuid4()
    retry_at = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

    added = await schedule_retry(delivery_id, retry_at, redis)  # type: ignore[arg-type]

    assert added == 1
    assert redis.zadd_calls == [("hookrelay:retries", {str(delivery_id): retry_at.timestamp()})]


async def test_promote_due_retries_calls_atomic_script() -> None:
    redis = RecordingRedis()
    now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

    promoted = await promote_due_retries(redis, now=now)  # type: ignore[arg-type]

    assert promoted == ["delivery-1"]
    assert redis.eval_calls[0][1:4] == (
        2,
        "hookrelay:retries",
        "hookrelay:deliveries",
    )
    assert redis.eval_calls[0][4] == now.timestamp()
