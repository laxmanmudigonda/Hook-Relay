import asyncio
import logging
import signal
from datetime import UTC, datetime

from prometheus_client import start_http_server
from sqlalchemy import select

from hookrelay.core.config import get_settings
from hookrelay.db.session import async_session_factory, dispose_engine
from hookrelay.models import OutboxEvent
from hookrelay.observability import OUTBOX_PUBLICATIONS, configure_logging
from hookrelay.queue.redis import close_redis, publish_delivery

logger = logging.getLogger("hookrelay.publisher")


async def publish_batch() -> int:
    settings = get_settings()
    async with async_session_factory() as session:
        async with session.begin():
            rows = list(
                await session.scalars(
                    select(OutboxEvent)
                    .where(OutboxEvent.published_at.is_(None))
                    .order_by(OutboxEvent.created_at, OutboxEvent.id)
                    .limit(settings.outbox_batch_size)
                    .with_for_update(skip_locked=True)
                )
            )
            for row in rows:
                try:
                    await publish_delivery(row.aggregate_id)
                except Exception as exc:
                    OUTBOX_PUBLICATIONS.labels("failed").inc()
                    row.publish_attempts += 1
                    row.last_error = f"{type(exc).__name__}: {exc}"[:500]
                    logger.exception("outbox publication failed", extra={"outbox_id": str(row.id)})
                    continue
                row.publish_attempts += 1
                OUTBOX_PUBLICATIONS.labels("published").inc()
                row.last_error = None
                row.published_at = datetime.now(UTC)
            return len(rows)


async def run_publisher() -> None:
    settings = get_settings()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_name, stop.set)
    logger.info("outbox publisher started")
    try:
        while not stop.is_set():
            await publish_batch()
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=settings.outbox_poll_interval_ms / 1000,
                )
            except TimeoutError:
                pass
    finally:
        await close_redis()
        await dispose_engine()
        logger.info("outbox publisher stopped")


def main() -> None:
    configure_logging()
    start_http_server(get_settings().publisher_metrics_port)
    asyncio.run(run_publisher())


if __name__ == "__main__":
    main()
