import pytest
from fastapi.testclient import TestClient

from hookrelay.main import app
from hookrelay.security import (
    decrypt_signing_secret,
    encrypt_signing_secret,
    validate_endpoint_url,
)


def test_signing_secret_is_encrypted_and_round_trips() -> None:
    plaintext = "a-secret-that-must-not-be-stored"

    encrypted = encrypt_signing_secret(plaintext)

    assert encrypted != plaintext
    assert plaintext not in encrypted
    assert decrypt_signing_secret(encrypted) == plaintext


async def test_private_endpoint_url_is_rejected_by_default() -> None:
    with pytest.raises(ValueError, match="private"):
        await validate_endpoint_url("http://127.0.0.1/webhook")


def test_oversized_api_body_is_rejected_before_route_processing() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/events",
            content=b"x" * 1_048_577,
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 413
    assert response.json() == {"detail": "request body too large"}
