import json
import logging

from fastapi.testclient import TestClient

from hookrelay.main import app
from hookrelay.observability import JsonFormatter


def test_json_formatter_emits_structured_fields() -> None:
    record = logging.LogRecord("hookrelay.test", logging.INFO, "", 0, "hello", (), None)
    record.delivery_id = "delivery-1"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["message"] == "hello"
    assert payload["delivery_id"] == "delivery-1"


def test_metrics_endpoint_and_request_id_are_exposed() -> None:
    with TestClient(app) as client:
        response = client.get("/metrics", headers={"X-Request-ID": "request-test-1"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "request-test-1"
    assert "hookrelay_http_requests_total" in response.text
