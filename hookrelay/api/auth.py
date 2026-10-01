import hashlib
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hookrelay.db.session import get_db_session
from hookrelay.models import ApiKey, Tenant

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def hash_api_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def get_current_tenant(
    api_key: Annotated[str | None, Depends(api_key_header)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Tenant:
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    tenant = await session.scalar(
        select(Tenant)
        .join(ApiKey, ApiKey.tenant_id == Tenant.id)
        .where(ApiKey.key_hash == hash_api_key(api_key), ApiKey.revoked_at.is_(None))
    )
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return tenant


CurrentTenant = Annotated[Tenant, Depends(get_current_tenant)]
