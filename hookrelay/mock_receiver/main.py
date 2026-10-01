import asyncio
from collections import defaultdict
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from hookrelay.delivery.signing import EVENT_ID_HEADER, verify_webhook_signature

app = FastAPI(title="HookRelay Mock Receiver", version="0.1.0")
flaky_counts: defaultdict[str, int] = defaultdict(int)
flaky_lock = asyncio.Lock()
signing_secrets: dict[str, str] = {}


class SigningSecretRegistration(BaseModel):
    secret: str = Field(min_length=32, max_length=255)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.put("/test/signing-secrets/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def register_signing_secret(key: str, registration: SigningSecretRegistration) -> None:
    signing_secrets[key] = registration.secret


@app.post("/webhooks/signed")
async def signed(
    request: Request,
    key: Annotated[str, Query(min_length=1, max_length=100)],
) -> dict[str, Any]:
    secret = signing_secrets.get(key)
    if secret is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown signing key")
    body = await request.body()
    if not verify_webhook_signature(secret, request.headers, body):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid signature")
    payload = await request.json()
    if request.headers.get(EVENT_ID_HEADER) != payload.get("id"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="event ID mismatch")
    return {"verified": True, "event_id": payload.get("id")}


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
