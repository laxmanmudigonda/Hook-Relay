from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hookrelay.api.auth import CurrentTenant
from hookrelay.db.session import get_db_session
from hookrelay.models import Delivery, DeliveryAttempt, DeliveryStatus, Event, WebhookEndpoint
from hookrelay.outbox import add_delivery_outbox
from hookrelay.schemas import DeliveryAttemptResponse, DeliveryResponse

router = APIRouter(prefix="/api/v1/deliveries", tags=["deliveries"])


async def owned_delivery(
    session: AsyncSession,
    delivery_id: UUID,
    tenant_id: UUID,
    *,
    for_update: bool = False,
) -> Delivery | None:
    statement = (
        select(Delivery)
        .join(Event, Event.id == Delivery.event_id)
        .where(
            Delivery.id == delivery_id,
            Event.tenant_id == tenant_id,
        )
    )
    if for_update:
        statement = statement.with_for_update(of=Delivery)
    return await session.scalar(statement)


async def delivery_response(session: AsyncSession, delivery: Delivery) -> DeliveryResponse:
    attempts = list(
        await session.scalars(
            select(DeliveryAttempt)
            .where(DeliveryAttempt.delivery_id == delivery.id)
            .order_by(DeliveryAttempt.attempt_number)
        )
    )
    return DeliveryResponse(
        **DeliveryResponse.model_validate(delivery).model_dump(exclude={"attempts"}),
        attempts=[DeliveryAttemptResponse.model_validate(item) for item in attempts],
    )


@router.get("/{delivery_id}", response_model=DeliveryResponse)
async def get_delivery(
    delivery_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    tenant: CurrentTenant,
) -> DeliveryResponse:
    delivery = await owned_delivery(session, delivery_id, tenant.id)
    if delivery is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="delivery not found")
    return await delivery_response(session, delivery)


@router.get("/{delivery_id}/attempts", response_model=list[DeliveryAttemptResponse])
async def list_attempts(
    delivery_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    tenant: CurrentTenant,
) -> list[DeliveryAttempt]:
    if await owned_delivery(session, delivery_id, tenant.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="delivery not found")
    return list(
        await session.scalars(
            select(DeliveryAttempt)
            .where(DeliveryAttempt.delivery_id == delivery_id)
            .order_by(DeliveryAttempt.attempt_number)
        )
    )


@router.post(
    "/{delivery_id}/replay",
    response_model=DeliveryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def replay_delivery(
    delivery_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    tenant: CurrentTenant,
) -> DeliveryResponse:
    delivery = await owned_delivery(session, delivery_id, tenant.id, for_update=True)
    if delivery is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="delivery not found")
    if delivery.status != DeliveryStatus.DEAD_LETTERED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="only dead-lettered deliveries can be replayed",
        )

    endpoint = await session.get(WebhookEndpoint, delivery.endpoint_id)
    if endpoint is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="endpoint no longer exists",
        )
    if not endpoint.enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="endpoint must be enabled before replay",
        )

    delivery.status = DeliveryStatus.PENDING.value
    delivery.current_attempt_count = 0
    delivery.replay_count += 1
    delivery.next_attempt_at = None
    delivery.processing_started_at = None
    delivery.delivered_at = None
    delivery.last_replayed_at = datetime.now(UTC)
    add_delivery_outbox(session, [delivery])
    await session.commit()
    await session.refresh(delivery)
    return await delivery_response(session, delivery)
