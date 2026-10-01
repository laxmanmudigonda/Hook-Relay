from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hookrelay.core.config import get_settings
from hookrelay.db.session import get_db_session
from hookrelay.models import WebhookEndpoint
from hookrelay.schemas import EndpointCreate, EndpointResponse

router = APIRouter(prefix="/api/v1/endpoints", tags=["endpoints"])


@router.post("", response_model=EndpointResponse, status_code=status.HTTP_201_CREATED)
async def create_endpoint(
    request: EndpointCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WebhookEndpoint:
    endpoint = WebhookEndpoint(
        tenant_id=get_settings().default_tenant_id,
        url=str(request.url),
        description=request.description,
        enabled=request.enabled,
    )
    session.add(endpoint)
    await session.commit()
    await session.refresh(endpoint)
    return endpoint


@router.get("", response_model=list[EndpointResponse])
async def list_endpoints(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[WebhookEndpoint]:
    result = await session.scalars(
        select(WebhookEndpoint)
        .where(WebhookEndpoint.tenant_id == get_settings().default_tenant_id)
        .order_by(WebhookEndpoint.created_at.desc(), WebhookEndpoint.id)
        .limit(limit)
        .offset(offset)
    )
    return list(result)


@router.get("/{endpoint_id}", response_model=EndpointResponse)
async def get_endpoint(
    endpoint_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WebhookEndpoint:
    endpoint = await session.scalar(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == endpoint_id,
            WebhookEndpoint.tenant_id == get_settings().default_tenant_id,
        )
    )
    if endpoint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="endpoint not found")
    return endpoint
