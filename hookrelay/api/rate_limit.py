from typing import Annotated

from fastapi import Depends, HTTPException, status
from redis.asyncio import Redis

from hookrelay.api.auth import CurrentTenant
from hookrelay.core.config import get_settings
from hookrelay.models import Tenant
from hookrelay.queue.redis import get_redis_client

RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return count
"""


async def enforce_rate_limit(
    tenant: CurrentTenant,
    redis: Annotated[Redis, Depends(get_redis_client)],
) -> Tenant:
    settings = get_settings()
    count = await redis.eval(RATE_LIMIT_SCRIPT, 1, f"hookrelay:rate:{tenant.id}", 60)
    if int(count) > settings.rate_limit_requests_per_minute:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit exceeded",
            headers={"Retry-After": "60"},
        )
    return tenant
