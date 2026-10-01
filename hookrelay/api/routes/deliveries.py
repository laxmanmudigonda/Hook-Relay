from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hookrelay.core.config import get_settings
from hookrelay.db.session import get_db_session
from hookrelay.models import Delivery, DeliveryAttempt, Event
from hookrelay.schemas import DeliveryAttemptResponse, DeliveryResponse

router = APIRouter(prefix="/api/v1/deliveries", tags=["deliveries"])


async def owned_delivery(session: AsyncSession, delivery_id: UUID) -> Delivery | None:
    return await session.scalar(
        select(Delivery)
        .join(Event, Event.id == Delivery.event_id)
        .where(
            Delivery.id == delivery_id,
            Event.tenant_id == get_settings().default_tenant_id,
        )
    )


@router.get("/{delivery_id}", response_model=DeliveryResponse)
async def get_delivery(
    delivery_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DeliveryResponse:
    delivery = await owned_delivery(session, delivery_id)
    if delivery is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="delivery not found")
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


@router.get("/{delivery_id}/attempts", response_model=list[DeliveryAttemptResponse])
async def list_attempts(
    delivery_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[DeliveryAttempt]:
    if await owned_delivery(session, delivery_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="delivery not found")
    return list(
        await session.scalars(
            select(DeliveryAttempt)
            .where(DeliveryAttempt.delivery_id == delivery_id)
            .order_by(DeliveryAttempt.attempt_number)
        )
    )
