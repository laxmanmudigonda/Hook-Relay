from functools import lru_cache
from uuid import UUID

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="HOOKRELAY_",
        extra="ignore",
    )

    app_name: str = "HookRelay"
    environment: str = "development"
    database_url: str = Field(
        default="postgresql+asyncpg://hookrelay:hookrelay@localhost:5432/hookrelay",
        description="SQLAlchemy async PostgreSQL connection URL",
    )
    database_echo: bool = False
    default_tenant_id: UUID = UUID("00000000-0000-0000-0000-000000000001")
    delivery_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    response_body_preview_bytes: int = Field(default=1024, ge=0, le=8192)
    redis_url: str = "redis://localhost:6379/0"
    redis_stream_name: str = "hookrelay:deliveries"
    redis_consumer_group: str = "hookrelay-workers"
    worker_block_ms: int = Field(default=5000, ge=100, le=60000)
    worker_batch_size: int = Field(default=10, ge=1, le=100)


@lru_cache
def get_settings() -> Settings:
    return Settings()
