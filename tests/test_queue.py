import uuid

from hookrelay.queue.redis import publish_delivery


class RecordingRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def xadd(self, stream: str, fields: dict[str, str]) -> str:
        self.calls.append((stream, fields))
        return "1-0"


async def test_publish_delivery_uses_stable_identifier() -> None:
    redis = RecordingRedis()
    delivery_id = uuid.uuid4()

    message_id = await publish_delivery(delivery_id, redis)  # type: ignore[arg-type]

    assert message_id == "1-0"
    assert redis.calls == [("hookrelay:deliveries", {"delivery_id": str(delivery_id)})]
