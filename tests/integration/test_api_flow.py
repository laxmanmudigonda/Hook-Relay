import os
import time
import uuid

import httpx
import pytest

API_BASE_URL = os.getenv("HOOKRELAY_INTEGRATION_BASE_URL")
RECEIVER_BASE_URL = os.getenv("HOOKRELAY_INTEGRATION_RECEIVER_URL", "http://mock-receiver:8001")

pytestmark = pytest.mark.skipif(
    API_BASE_URL is None,
    reason="set HOOKRELAY_INTEGRATION_BASE_URL to run Compose integration tests",
)


def wait_for_terminal_delivery(client: httpx.Client, delivery_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/deliveries/{delivery_id}")
        assert response.status_code == 200
        delivery = response.json()
        if delivery["status"] != "pending":
            return delivery
        time.sleep(0.1)
    pytest.fail(f"delivery {delivery_id} did not reach a terminal state")


def test_asynchronous_delivery_and_idempotency() -> None:
    assert API_BASE_URL is not None
    key = f"integration-{uuid.uuid4()}"

    with httpx.Client(base_url=API_BASE_URL, timeout=15) as client:
        success_endpoint = client.post(
            "/api/v1/endpoints",
            json={"url": f"{RECEIVER_BASE_URL}/webhooks/success"},
        )
        failure_endpoint = client.post(
            "/api/v1/endpoints",
            json={"url": f"{RECEIVER_BASE_URL}/webhooks/fail"},
        )
        assert success_endpoint.status_code == 201
        assert failure_endpoint.status_code == 201

        request = {
            "event_type": "payment.completed",
            "payload": {"payment_id": "pay_integration", "amount": 2499},
        }
        first = client.post(
            "/api/v1/events",
            headers={"Idempotency-Key": key},
            json=request,
        )
        repeated = client.post(
            "/api/v1/events",
            headers={"Idempotency-Key": key},
            json=request,
        )

        assert first.status_code == 201
        assert repeated.status_code == 200
        assert repeated.json()["id"] == first.json()["id"]

        conflicting = client.post(
            "/api/v1/events",
            headers={"Idempotency-Key": key},
            json={**request, "payload": {"payment_id": "different"}},
        )
        assert conflicting.status_code == 409

        deliveries_by_endpoint = {item["endpoint_id"]: item for item in first.json()["deliveries"]}
        success_delivery = deliveries_by_endpoint[success_endpoint.json()["id"]]
        failure_delivery = deliveries_by_endpoint[failure_endpoint.json()["id"]]
        success_detail = wait_for_terminal_delivery(client, success_delivery["id"])
        failure_detail = wait_for_terminal_delivery(client, failure_delivery["id"])
        assert success_detail["status"] == "delivered"
        assert failure_detail["status"] == "failed"

        for detail in (success_detail, failure_detail):
            assert len(detail["attempts"]) == 1
