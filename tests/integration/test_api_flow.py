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
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/deliveries/{delivery_id}")
        assert response.status_code == 200
        delivery = response.json()
        if delivery["status"] in {"delivered", "failed", "dead_lettered"}:
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
        flaky_endpoint = client.post(
            "/api/v1/endpoints",
            json={"url": f"{RECEIVER_BASE_URL}/webhooks/flaky?key={key}&failures=2"},
        )
        replay_endpoint = client.post(
            "/api/v1/endpoints",
            json={"url": f"{RECEIVER_BASE_URL}/webhooks/flaky?key=replay-{key}&failures=5"},
        )
        assert success_endpoint.status_code == 201
        assert failure_endpoint.status_code == 201
        assert flaky_endpoint.status_code == 201
        assert replay_endpoint.status_code == 201

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
        flaky_delivery = deliveries_by_endpoint[flaky_endpoint.json()["id"]]
        replay_delivery = deliveries_by_endpoint[replay_endpoint.json()["id"]]
        success_detail = wait_for_terminal_delivery(client, success_delivery["id"])
        failure_detail = wait_for_terminal_delivery(client, failure_delivery["id"])
        flaky_detail = wait_for_terminal_delivery(client, flaky_delivery["id"])
        replay_dead_letter = wait_for_terminal_delivery(client, replay_delivery["id"])
        assert success_detail["status"] == "delivered"
        assert failure_detail["status"] == "dead_lettered"
        assert flaky_detail["status"] == "delivered"
        assert replay_dead_letter["status"] == "dead_lettered"
        assert len(success_detail["attempts"]) == 1
        assert len(failure_detail["attempts"]) == 5
        assert len(flaky_detail["attempts"]) == 3
        assert len(replay_dead_letter["attempts"]) == 5

        replayed = client.post(f"/api/v1/deliveries/{replay_delivery['id']}/replay")
        assert replayed.status_code == 202
        assert replayed.json()["status"] == "pending"
        assert replayed.json()["replay_count"] == 1

        replay_success = wait_for_terminal_delivery(client, replay_delivery["id"])
        assert replay_success["status"] == "delivered"
        assert replay_success["attempt_count"] == 6
        assert replay_success["current_attempt_count"] == 1
        assert replay_success["replay_count"] == 1
        assert [attempt["attempt_number"] for attempt in replay_success["attempts"]] == list(
            range(1, 7)
        )

        replay_again = client.post(f"/api/v1/deliveries/{replay_delivery['id']}/replay")
        assert replay_again.status_code == 409

        for endpoint in (success_endpoint, failure_endpoint, flaky_endpoint, replay_endpoint):
            disabled = client.patch(
                f"/api/v1/endpoints/{endpoint.json()['id']}",
                json={"enabled": False},
            )
            assert disabled.status_code == 200
