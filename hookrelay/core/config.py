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
    development_api_key: str = "hr_dev_local_change_me"
    delivery_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    response_body_preview_bytes: int = Field(default=1024, ge=0, le=8192)
    redis_url: str = "redis://localhost:6379/0"
    redis_stream_name: str = "hookrelay:deliveries"
    redis_consumer_group: str = "hookrelay-workers"
    worker_block_ms: int = Field(default=5000, ge=100, le=60000)
    worker_batch_size: int = Field(default=10, ge=1, le=100)
    worker_claim_idle_ms: int = Field(default=30000, ge=1000, le=3600000)
    worker_claim_interval_ms: int = Field(default=5000, ge=100, le=60000)
    max_delivery_attempts: int = Field(default=5, ge=1, le=100)
    retry_base_delay_seconds: float = Field(default=1.0, gt=0, le=3600)
    retry_max_delay_seconds: float = Field(default=60.0, gt=0, le=86400)
    retry_schedule_name: str = "hookrelay:retries"
    retry_scheduler_interval_ms: int = Field(default=500, ge=100, le=60000)
    retry_promotion_batch_size: int = Field(default=100, ge=1, le=1000)
    outbox_poll_interval_ms: int = Field(default=500, ge=50, le=60000)
    outbox_batch_size: int = Field(default=100, ge=1, le=1000)


@lru_cache
def get_settings() -> Settings:
    return Settings()
