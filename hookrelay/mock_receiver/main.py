import asyncio
from collections import defaultdict
from typing import Annotated, Any

from fastapi import FastAPI, Query, Response, status

app = FastAPI(title="HookRelay Mock Receiver", version="0.1.0")
flaky_counts: defaultdict[str, int] = defaultdict(int)
flaky_lock = asyncio.Lock()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhooks/success")
async def success(payload: dict[str, Any]) -> dict[str, Any]:
    return {"received": True, "event_id": payload.get("id")}


@app.post("/webhooks/fail", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
async def fail() -> dict[str, str]:
    return {"detail": "simulated failure"}


@app.post("/webhooks/flaky")
async def flaky(
    response: Response,
    key: Annotated[str, Query(min_length=1, max_length=100)] = "default",
    failures: Annotated[int, Query(ge=0, le=100)] = 2,
) -> dict[str, Any]:
    async with flaky_lock:
        flaky_counts[key] += 1
        attempt = flaky_counts[key]
    if attempt <= failures:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"detail": "simulated transient failure", "attempt": attempt}
    return {"received": True, "attempt": attempt}


@app.post("/webhooks/slow")
async def slow(
    delay_seconds: Annotated[float, Query(gt=0, le=30)] = 10,
) -> dict[str, bool]:
    await asyncio.sleep(delay_seconds)
    return {"received": True}


@app.post("/webhooks/rate-limited", status_code=status.HTTP_429_TOO_MANY_REQUESTS)
async def rate_limited(
    response: Response,
    retry_after: Annotated[int, Query(ge=1, le=3600)] = 5,
) -> dict[str, str]:
    response.headers["Retry-After"] = str(retry_after)
    return {"detail": "simulated rate limit"}
