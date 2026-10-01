from hookrelay.delivery.signing import build_signature_headers, verify_webhook_signature

SECRET = "unit-test-signing-secret-with-at-least-32-bytes"
BODY = b'{"id":"evt_123","type":"payment.completed"}'
TIMESTAMP = 1_800_000_000


def test_valid_signature_verifies() -> None:
    headers = build_signature_headers(SECRET, "evt_123", BODY, timestamp=TIMESTAMP)

    assert verify_webhook_signature(SECRET, headers, BODY, now=TIMESTAMP)


def test_modified_body_and_wrong_secret_fail_verification() -> None:
    headers = build_signature_headers(SECRET, "evt_123", BODY, timestamp=TIMESTAMP)

    assert not verify_webhook_signature(SECRET, headers, BODY + b" ", now=TIMESTAMP)
    assert not verify_webhook_signature("wrong-secret", headers, BODY, now=TIMESTAMP)


def test_expired_and_future_timestamps_fail_verification() -> None:
    old_headers = build_signature_headers(SECRET, "evt_123", BODY, timestamp=TIMESTAMP - 301)
    future_headers = build_signature_headers(SECRET, "evt_123", BODY, timestamp=TIMESTAMP + 301)

    assert not verify_webhook_signature(SECRET, old_headers, BODY, now=TIMESTAMP)
    assert not verify_webhook_signature(SECRET, future_headers, BODY, now=TIMESTAMP)


def test_missing_or_malformed_headers_fail_verification() -> None:
    assert not verify_webhook_signature(SECRET, {}, BODY, now=TIMESTAMP)
    assert not verify_webhook_signature(
        SECRET,
        {"X-HookRelay-Signature": "v1=nope", "X-HookRelay-Timestamp": "not-a-time"},
        BODY,
        now=TIMESTAMP,
    )
