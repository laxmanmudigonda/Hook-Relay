import asyncio
import logging
import os
import signal
import socket
from typing import Any
from uuid import UUID

import httpx
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from hookrelay.core.config import get_settings
from hookrelay.db.session import async_session_factory, dispose_engine
from hookrelay.delivery.service import attempt_delivery
from hookrelay.models import Delivery, DeliveryStatus, Event, WebhookEndpoint

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
        delivery = await session.get(Delivery, delivery_id)
        if delivery is None:
            logger.warning(
                "acknowledging message for missing delivery",
                extra={"delivery_id": str(delivery_id), "message_id": message_id},
            )
            await acknowledge(redis, message_id)
            return
        if delivery.status != DeliveryStatus.PENDING.value:
            logger.info(
                "acknowledging duplicate message for terminal delivery",
                extra={
                    "delivery_id": str(delivery.id),
                    "message_id": message_id,
                    "status": delivery.status,
                },
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
        await acknowledge(redis, message_id)
        logger.info(
            "delivery processed",
            extra={
                "delivery_id": str(delivery.id),
                "event_id": str(event.id),
                "endpoint_id": str(endpoint.id),
                "message_id": message_id,
                "status": delivery.status,
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
            while not stop.is_set():
                messages = await redis.xreadgroup(
                    groupname=settings.redis_consumer_group,
                    consumername=consumer_name,
                    streams={settings.redis_stream_name: ">"},
                    count=settings.worker_batch_size,
                    block=settings.worker_block_ms,
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
