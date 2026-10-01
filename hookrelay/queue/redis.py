from uuid import UUID

from redis.asyncio import Redis

from hookrelay.core.config import get_settings

settings = get_settings()
redis_client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)


async def get_redis_client() -> Redis:
    return redis_client


async def publish_delivery(delivery_id: UUID, client: Redis | None = None) -> str:
    active_client = client or redis_client
    return await active_client.xadd(
        settings.redis_stream_name,
        {"delivery_id": str(delivery_id)},
    )


async def close_redis() -> None:
    await redis_client.aclose()
