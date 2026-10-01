from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from hookrelay.api.routes.deliveries import router as deliveries_router
from hookrelay.api.routes.endpoints import router as endpoints_router
from hookrelay.api.routes.events import router as events_router
from hookrelay.api.routes.health import router as health_router
from hookrelay.core.config import get_settings
from hookrelay.db.session import dispose_engine
from hookrelay.queue.redis import close_redis


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await close_redis()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(health_router)
    application.include_router(endpoints_router)
    application.include_router(events_router)
    application.include_router(deliveries_router)
    return application


app = create_app()
