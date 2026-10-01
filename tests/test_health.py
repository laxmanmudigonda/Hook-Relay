from collections.abc import AsyncIterator

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from hookrelay.db.session import get_db_session
from hookrelay.main import app
from hookrelay.queue.redis import get_redis_client


class HealthySession:
    async def execute(self, _statement: object) -> None:
        return None


class UnhealthySession:
    async def execute(self, _statement: object) -> None:
        raise ConnectionError("database is unavailable")


class HealthyRedis:
    async def ping(self) -> bool:
        return True


class UnhealthyRedis:
    async def ping(self) -> bool:
        raise ConnectionError("redis is unavailable")


def override_session(session: object):
    async def dependency() -> AsyncIterator[AsyncSession]:
        yield session  # type: ignore[misc]

    return dependency


def test_health_reports_process_liveness() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_healthy_database() -> None:
    app.dependency_overrides[get_db_session] = override_session(HealthySession())
    app.dependency_overrides[get_redis_client] = lambda: HealthyRedis()
    try:
        with TestClient(app) as client:
            response = client.get("/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok", "redis": "ok"}


def test_readiness_returns_503_when_database_is_unavailable() -> None:
    app.dependency_overrides[get_db_session] = override_session(UnhealthySession())
    app.dependency_overrides[get_redis_client] = lambda: HealthyRedis()
    try:
        with TestClient(app) as client:
            response = client.get("/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}


def test_readiness_returns_503_when_redis_is_unavailable() -> None:
    app.dependency_overrides[get_db_session] = override_session(HealthySession())
    app.dependency_overrides[get_redis_client] = lambda: UnhealthyRedis()
    try:
        with TestClient(app) as client:
            response = client.get("/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "redis unavailable"}
