from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis

from hookrelay.core.config import get_settings

settings = get_settings()
redis_client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)

PROMOTE_DUE_RETRIES_SCRIPT = """
local due = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, ARGV[2])
for _, delivery_id in ipairs(due) do
    if redis.call('ZREM', KEYS[1], delivery_id) == 1 then
        redis.call('XADD', KEYS[2], '*', 'delivery_id', delivery_id)
    end
end
return due
"""


async def get_redis_client() -> Redis:
    return redis_client


async def publish_delivery(delivery_id: UUID, client: Redis | None = None) -> str:
    active_client = client or redis_client
    return await active_client.xadd(
        settings.redis_stream_name,
        {"delivery_id": str(delivery_id)},
    )


async def schedule_retry(
    delivery_id: UUID,
    retry_at: datetime,
    client: Redis | None = None,
) -> int:
    active_client = client or redis_client
    return await active_client.zadd(
        settings.retry_schedule_name,
        {str(delivery_id): retry_at.timestamp()},
    )


async def promote_due_retries(
    client: Redis | None = None,
    *,
    now: datetime | None = None,
) -> list[str]:
    active_client = client or redis_client
    current = now or datetime.now(UTC)
    result = await active_client.eval(
        PROMOTE_DUE_RETRIES_SCRIPT,
        2,
        settings.retry_schedule_name,
        settings.redis_stream_name,
        current.timestamp(),
        settings.retry_promotion_batch_size,
    )
    return [str(delivery_id) for delivery_id in result]


async def close_redis() -> None:
    await redis_client.aclose()
