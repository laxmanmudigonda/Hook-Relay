import hashlib
import hmac
import time
from collections.abc import Mapping

SIGNATURE_VERSION = "v1"
SIGNATURE_HEADER = "X-HookRelay-Signature"
TIMESTAMP_HEADER = "X-HookRelay-Timestamp"
EVENT_ID_HEADER = "X-HookRelay-Event-ID"
DEFAULT_TIMESTAMP_TOLERANCE_SECONDS = 300


def sign_webhook_payload(secret: str, timestamp: int, body: bytes) -> str:
    signed_payload = str(timestamp).encode("ascii") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_VERSION}={digest}"


def build_signature_headers(
    secret: str,
    event_id: str,
    body: bytes,
    *,
    timestamp: int | None = None,
) -> dict[str, str]:
    issued_at = int(time.time()) if timestamp is None else timestamp
    return {
        SIGNATURE_HEADER: sign_webhook_payload(secret, issued_at, body),
        TIMESTAMP_HEADER: str(issued_at),
        EVENT_ID_HEADER: event_id,
        "Content-Type": "application/json",
    }


def verify_webhook_signature(
    secret: str,
    headers: Mapping[str, str],
    body: bytes,
    *,
    tolerance_seconds: int = DEFAULT_TIMESTAMP_TOLERANCE_SECONDS,
    now: int | None = None,
) -> bool:
    if tolerance_seconds < 0:
        raise ValueError("tolerance_seconds must be nonnegative")
    signature = headers.get(SIGNATURE_HEADER)
    timestamp_value = headers.get(TIMESTAMP_HEADER)
    if signature is None or timestamp_value is None:
        return False
    try:
        timestamp = int(timestamp_value)
    except ValueError:
        return False
    current = int(time.time()) if now is None else now
    if abs(current - timestamp) > tolerance_seconds:
        return False
    expected = sign_webhook_payload(secret, timestamp, body)
    return hmac.compare_digest(signature, expected)
