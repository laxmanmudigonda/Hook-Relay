import httpx

from hookrelay.worker import process_message


class AcknowledgingRedis:
    def __init__(self) -> None:
        self.acknowledged: list[tuple[str, str, str]] = []

    async def xack(self, stream: str, group: str, message_id: str) -> int:
        self.acknowledged.append((stream, group, message_id))
        return 1


async def test_worker_acknowledges_malformed_message() -> None:
    redis = AcknowledgingRedis()
    async with httpx.AsyncClient() as client:
        await process_message(  # type: ignore[arg-type]
            redis,
            client,
            "123-0",
            {"delivery_id": "not-a-uuid"},
        )

    assert redis.acknowledged == [("hookrelay:deliveries", "hookrelay-workers", "123-0")]
