import asyncio
import logging
import os
import signal
import socket
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy import and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from hookrelay.core.config import get_settings
from hookrelay.db.session import async_session_factory, dispose_engine
from hookrelay.delivery.service import attempt_delivery
from hookrelay.models import Delivery, DeliveryStatus, Event, WebhookEndpoint
from hookrelay.queue.redis import promote_due_retries, reclaim_abandoned, schedule_retry

logger = logging.getLogger("hookrelay.worker")


async def ensure_consumer_group(client: Redis) -> None:
    settings = get_settings()
    try:
        await client.xgroup_create(
            settings.redis_stream_name,
            settings.redis_consumer_group,
            id="0",
            mkstream=True,
        )
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def acknowledge(client: Redis, message_id: str) -> None:
    settings = get_settings()
    await client.xack(
        settings.redis_stream_name,
        settings.redis_consumer_group,
        message_id,
    )


async def claim_delivery(session: AsyncSession, delivery_id: UUID) -> Delivery | None:
    """Atomically acquire work or take over a stale processing lease."""
    settings = get_settings()
    now = datetime.now(UTC)
    stale_before = now - timedelta(milliseconds=settings.worker_claim_idle_ms)
    claimed_id = await session.scalar(
        update(Delivery)
        .where(
            Delivery.id == delivery_id,
            or_(
                Delivery.status == DeliveryStatus.PENDING.value,
                and_(
                    Delivery.status == DeliveryStatus.RETRY_SCHEDULED.value,
                    Delivery.next_attempt_at.is_not(None),
                    Delivery.next_attempt_at <= now,
                ),
                and_(
                    Delivery.status == DeliveryStatus.PROCESSING.value,
                    Delivery.processing_started_at.is_not(None),
                    Delivery.processing_started_at <= stale_before,
                ),
            ),
        )
        .values(
            status=DeliveryStatus.PROCESSING.value,
            processing_started_at=now,
            next_attempt_at=None,
        )
        .returning(Delivery.id)
    )
    if claimed_id is None:
        await session.rollback()
        return None
    await session.commit()
    return await session.get(Delivery, claimed_id)


async def process_message(
    redis: Redis,
    http_client: httpx.AsyncClient,
    message_id: str,
    fields: dict[str, Any],
) -> None:
    raw_delivery_id = fields.get("delivery_id")
    try:
        delivery_id = UUID(str(raw_delivery_id))
    except (TypeError, ValueError):
        logger.error("discarding malformed queue message", extra={"message_id": message_id})
        await acknowledge(redis, message_id)
        return

    async with async_session_factory() as session:
        delivery = await claim_delivery(session, delivery_id)
        if delivery is None:
            existing = await session.get(Delivery, delivery_id)
            if (
                existing is not None
                and existing.status == DeliveryStatus.RETRY_SCHEDULED.value
                and existing.next_attempt_at is not None
            ):
                await schedule_retry(existing.id, existing.next_attempt_at, redis)
            logger.info(
                "acknowledging message that is terminal, scheduled, or already processing",
                extra={"delivery_id": str(delivery_id), "message_id": message_id},
            )
            await acknowledge(redis, message_id)
            return

        event = await session.get(Event, delivery.event_id)
        endpoint = await session.get(WebhookEndpoint, delivery.endpoint_id)
        if event is None or endpoint is None:
            logger.error(
                "delivery references missing domain records",
                extra={"delivery_id": str(delivery.id), "message_id": message_id},
            )
            await acknowledge(redis, message_id)
            return

        await attempt_delivery(session, http_client, delivery, event, endpoint)
        if (
            delivery.status == DeliveryStatus.RETRY_SCHEDULED.value
            and delivery.next_attempt_at is not None
        ):
            await schedule_retry(delivery.id, delivery.next_attempt_at, redis)
        await acknowledge(redis, message_id)
        logger.info(
            "delivery processed",
            extra={
                "delivery_id": str(delivery.id),
                "event_id": str(event.id),
                "endpoint_id": str(endpoint.id),
                "message_id": message_id,
                "status": delivery.status,
                "attempt_count": delivery.attempt_count,
                "current_attempt_count": delivery.current_attempt_count,
                "next_attempt_at": (
                    delivery.next_attempt_at.isoformat() if delivery.next_attempt_at else None
                ),
            },
        )


async def run_worker() -> None:
    settings = get_settings()
    consumer_name = os.getenv("HOOKRELAY_WORKER_NAME", f"{socket.gethostname()}-{os.getpid()}")
    redis: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_name, stop.set)

    await ensure_consumer_group(redis)
    logger.info("worker started", extra={"consumer_name": consumer_name})

    try:
        async with httpx.AsyncClient(
            timeout=settings.delivery_timeout_seconds,
            follow_redirects=False,
        ) as http_client:
            last_claim_at = 0.0
            while not stop.is_set():
                promoted = await promote_due_retries(redis)
                if promoted:
                    logger.info("promoted due retries", extra={"count": len(promoted)})
                now = loop.time()
                if now - last_claim_at >= settings.worker_claim_interval_ms / 1000:
                    reclaimed = await reclaim_abandoned(consumer_name, redis)
                    last_claim_at = now
                    if reclaimed:
                        logger.info("reclaimed abandoned messages", extra={"count": len(reclaimed)})
                    for message_id, fields in reclaimed:
                        try:
                            await process_message(redis, http_client, message_id, fields)
                        except Exception:
                            logger.exception(
                                "reclaimed delivery processing failed before acknowledgement",
                                extra={"message_id": message_id},
                            )
                messages = await redis.xreadgroup(
                    groupname=settings.redis_consumer_group,
                    consumername=consumer_name,
                    streams={settings.redis_stream_name: ">"},
                    count=settings.worker_batch_size,
                    block=min(settings.worker_block_ms, settings.retry_scheduler_interval_ms),
                )
                for _stream, entries in messages:
                    for message_id, fields in entries:
                        try:
                            await process_message(redis, http_client, message_id, fields)
                        except Exception:
                            logger.exception(
                                "delivery processing failed before acknowledgement",
                                extra={"message_id": message_id},
                            )
    finally:
        await redis.aclose()
        await dispose_engine()
        logger.info("worker stopped")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
