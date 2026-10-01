import uuid
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hookrelay.core.config import get_settings
from hookrelay.db.session import get_db_session
from hookrelay.models import Delivery, DeliveryStatus, Event, WebhookEndpoint
from hookrelay.queue.redis import publish_delivery
from hookrelay.schemas import DeliverySummary, EventCreate, EventResponse

router = APIRouter(prefix="/api/v1/events", tags=["events"])


async def publish_pending_deliveries(deliveries: list[Delivery], event_id: UUID) -> None:
    try:
        for delivery in deliveries:
            if delivery.status in {
                DeliveryStatus.PENDING.value,
                DeliveryStatus.RETRY_SCHEDULED.value,
            }:
                await publish_delivery(delivery.id)
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "event persisted but delivery queue is unavailable",
                "event_id": str(event_id),
            },
        ) from exc


async def event_response(session: AsyncSession, event: Event) -> EventResponse:
    deliveries = list(
        await session.scalars(
            select(Delivery)
            .where(Delivery.event_id == event.id)
            .order_by(Delivery.created_at, Delivery.id)
        )
    )
    return EventResponse(
        id=event.id,
        event_type=event.event_type,
        payload=event.payload,
        idempotency_key=event.idempotency_key,
        created_at=event.created_at,
        deliveries=[DeliverySummary.model_validate(item) for item in deliveries],
    )


@router.post("", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    request: EventCreate,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=1, max_length=255)
    ] = None,
) -> EventResponse:
    tenant_id = get_settings().default_tenant_id

    if idempotency_key is not None:
        event_id = uuid.uuid4()
        inserted_id = await session.scalar(
            insert(Event)
            .values(
                id=event_id,
                tenant_id=tenant_id,
                event_type=request.event_type,
                payload=request.payload,
                idempotency_key=idempotency_key,
            )
            .on_conflict_do_nothing(constraint="uq_events_tenant_idempotency")
            .returning(Event.id)
        )
        if inserted_id is None:
            existing = await session.scalar(
                select(Event).where(
                    Event.tenant_id == tenant_id,
                    Event.idempotency_key == idempotency_key,
                )
            )
            if existing is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="idempotency conflict",
                )
            if existing.event_type != request.event_type or existing.payload != request.payload:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="idempotency key was already used with a different event",
                )
            existing_deliveries = list(
                await session.scalars(select(Delivery).where(Delivery.event_id == existing.id))
            )
            await publish_pending_deliveries(existing_deliveries, existing.id)
            response.status_code = status.HTTP_200_OK
            return await event_response(session, existing)
        event = await session.get(Event, inserted_id)
        if event is None:
            raise RuntimeError("inserted event could not be loaded")
    else:
        event = Event(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            event_type=request.event_type,
            payload=request.payload,
            idempotency_key=None,
        )
        session.add(event)
        await session.flush()

    endpoints = list(
        await session.scalars(
            select(WebhookEndpoint).where(
                WebhookEndpoint.tenant_id == tenant_id,
                WebhookEndpoint.enabled.is_(True),
            )
        )
    )
    deliveries = [
        Delivery(id=uuid.uuid4(), event_id=event.id, endpoint_id=endpoint.id)
        for endpoint in endpoints
    ]
    session.add_all(deliveries)
    await session.commit()
    await session.refresh(event)

    await publish_pending_deliveries(deliveries, event.id)

    return await event_response(session, event)


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> EventResponse:
    event = await session.scalar(
        select(Event).where(
            Event.id == event_id,
            Event.tenant_id == get_settings().default_tenant_id,
        )
    )
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="event not found")
    return await event_response(session, event)
