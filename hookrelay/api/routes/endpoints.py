from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hookrelay.api.auth import CurrentTenant
from hookrelay.db.session import get_db_session
from hookrelay.models import WebhookEndpoint, generate_signing_secret
from hookrelay.schemas import (
    EndpointCreate,
    EndpointCreatedResponse,
    EndpointResponse,
    EndpointUpdate,
)
from hookrelay.security import encrypt_signing_secret, validate_endpoint_url

router = APIRouter(prefix="/api/v1/endpoints", tags=["endpoints"])


@router.post("", response_model=EndpointCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_endpoint(
    request: EndpointCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    tenant: CurrentTenant,
) -> EndpointCreatedResponse:
    try:
        await validate_endpoint_url(str(request.url))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    signing_secret = generate_signing_secret()
    endpoint = WebhookEndpoint(
        tenant_id=tenant.id,
        url=str(request.url),
        description=request.description,
        enabled=request.enabled,
        signing_secret=encrypt_signing_secret(signing_secret),
    )
    session.add(endpoint)
    await session.commit()
    await session.refresh(endpoint)
    return EndpointCreatedResponse(
        **EndpointResponse.model_validate(endpoint).model_dump(),
        signing_secret=signing_secret,
    )


@router.get("", response_model=list[EndpointResponse])
async def list_endpoints(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    tenant: CurrentTenant,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[WebhookEndpoint]:
    result = await session.scalars(
        select(WebhookEndpoint)
        .where(WebhookEndpoint.tenant_id == tenant.id)
        .order_by(WebhookEndpoint.created_at.desc(), WebhookEndpoint.id)
        .limit(limit)
        .offset(offset)
    )
    return list(result)


@router.get("/{endpoint_id}", response_model=EndpointResponse)
async def get_endpoint(
    endpoint_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    tenant: CurrentTenant,
) -> WebhookEndpoint:
    endpoint = await session.scalar(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == endpoint_id,
            WebhookEndpoint.tenant_id == tenant.id,
        )
    )
    if endpoint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="endpoint not found")
    return endpoint


@router.patch("/{endpoint_id}", response_model=EndpointResponse)
async def update_endpoint(
    endpoint_id: UUID,
    request: EndpointUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    tenant: CurrentTenant,
) -> WebhookEndpoint:
    endpoint = await session.scalar(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == endpoint_id,
            WebhookEndpoint.tenant_id == tenant.id,
        )
    )
    if endpoint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="endpoint not found")
    endpoint.enabled = request.enabled
    await session.commit()
    await session.refresh(endpoint)
    return endpoint
