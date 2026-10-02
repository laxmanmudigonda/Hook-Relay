import asyncio
import base64
import hashlib
import ipaddress
import json
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken

from hookrelay.core.config import get_settings


def _fernet() -> Fernet:
    raw_key = get_settings().signing_encryption_key.encode("utf-8")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw_key).digest()))


def encrypt_signing_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode("utf-8")).decode("ascii")


def decrypt_signing_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        # Compatibility for endpoints created before encryption was introduced.
        return value


async def validate_endpoint_url(url: str) -> None:
    settings = get_settings()
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("endpoint URL must use HTTP or HTTPS")
    if settings.allow_private_endpoint_urls:
        return
    if parsed.hostname.lower() == "localhost":
        raise ValueError("private endpoint URLs are not allowed")
    loop = asyncio.get_running_loop()
    try:
        addresses = await loop.getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError("endpoint hostname could not be resolved") from exc
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("private endpoint URLs are not allowed")


class RequestSizeLimitMiddleware:
    def __init__(self, app: Callable[..., Awaitable[None]], max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/v1"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length and int(content_length) > self.max_bytes:
            await self._reject(send)
            return
        messages: list[dict] = []
        size = 0
        while True:
            message = await receive()
            messages.append(message)
            size += len(message.get("body", b""))
            if size > self.max_bytes:
                await self._reject(send)
                return
            if not message.get("more_body", False):
                break

        async def replay() -> dict:
            return messages.pop(0) if messages else {"type": "http.request", "body": b""}

        await self.app(scope, replay, send)

    @staticmethod
    async def _reject(send: Callable) -> None:
        body = json.dumps({"detail": "request body too large"}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
