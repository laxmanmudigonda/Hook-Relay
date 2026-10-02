import contextvars
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

HTTP_REQUESTS = Counter(
    "hookrelay_http_requests_total",
    "HTTP requests handled",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "hookrelay_http_request_duration_seconds",
    "HTTP request duration",
    ("method", "route"),
)
DELIVERY_ATTEMPTS = Counter(
    "hookrelay_delivery_attempts_total",
    "Webhook delivery attempts",
    ("result",),
)
DELIVERY_DURATION = Histogram(
    "hookrelay_delivery_duration_seconds",
    "Webhook receiver latency",
    ("result",),
)
OUTBOX_PUBLICATIONS = Counter(
    "hookrelay_outbox_publications_total",
    "Outbox publication attempts",
    ("result",),
)
RECLAIMED_MESSAGES = Counter(
    "hookrelay_reclaimed_messages_total",
    "Redis messages reclaimed from dead workers",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        for key in (
            "tenant_id",
            "event_id",
            "delivery_id",
            "endpoint_id",
            "message_id",
            "status",
            "attempt_count",
            "count",
            "method",
            "path",
            "status_code",
            "duration_ms",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


async def observe_request(request: Request, call_next: Any) -> Response:
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))[:128]
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        duration = time.perf_counter() - started
        status = str(locals().get("status_code", 500))
        route_path = locals().get("route_path", "unmatched")
        HTTP_REQUESTS.labels(request.method, route_path, status).inc()
        HTTP_DURATION.labels(request.method, route_path).observe(duration)
        logging.getLogger("hookrelay.api").info(
            "request completed",
            extra={
                "method": request.method,
                "path": route_path,
                "status_code": status,
                "duration_ms": round(duration * 1000),
            },
        )
        request_id_var.reset(token)


router = APIRouter(tags=["observability"])


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
