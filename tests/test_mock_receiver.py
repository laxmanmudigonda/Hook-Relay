import uuid

from fastapi.testclient import TestClient

from hookrelay.delivery.signing import build_signature_headers
from hookrelay.mock_receiver.main import app


def test_success_receiver_echoes_event_id() -> None:
    with TestClient(app) as client:
        response = client.post("/webhooks/success", json={"id": "evt_123"})

    assert response.status_code == 200
    assert response.json() == {"received": True, "event_id": "evt_123"}


def test_failure_receiver_is_deterministic() -> None:
    with TestClient(app) as client:
        response = client.post("/webhooks/fail", json={})

    assert response.status_code == 500


def test_flaky_receiver_recovers_after_configured_failures() -> None:
    key = str(uuid.uuid4())
    with TestClient(app) as client:
        statuses = [
            client.post(f"/webhooks/flaky?key={key}&failures=2", json={}).status_code
            for _ in range(3)
        ]

    assert statuses == [500, 500, 200]


def test_signed_receiver_verifies_exact_body() -> None:
    key = str(uuid.uuid4())
    secret = "mock-receiver-signing-secret-at-least-32-bytes"
    body = b'{"id":"evt_signed","type":"test","data":{}}'
    headers = build_signature_headers(secret, "evt_signed", body)

    with TestClient(app) as client:
        registered = client.put(f"/test/signing-secrets/{key}", json={"secret": secret})
        accepted = client.post(f"/webhooks/signed?key={key}", content=body, headers=headers)
        rejected = client.post(
            f"/webhooks/signed?key={key}",
            content=body + b" ",
            headers=headers,
        )

    assert registered.status_code == 204
    assert accepted.status_code == 200
    assert accepted.json() == {"verified": True, "event_id": "evt_signed"}
    assert rejected.status_code == 401
