from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator


class EndpointCreate(BaseModel):
    url: AnyHttpUrl
    description: str | None = Field(default=None, max_length=500)
    enabled: bool = True

    @field_validator("url")
    @classmethod
    def reject_url_credentials(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.username or value.password:
            raise ValueError("URL credentials are not allowed")
        return value


class EndpointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    url: str
    description: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class EndpointUpdate(BaseModel):
    enabled: bool


class EventCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
    payload: dict[str, Any]


class DeliverySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    endpoint_id: UUID
    status: str
    attempt_count: int
    delivered_at: datetime | None
    next_attempt_at: datetime | None
    created_at: datetime


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: str
    payload: dict[str, Any]
    idempotency_key: str | None
    created_at: datetime
    deliveries: list[DeliverySummary] = Field(default_factory=list)


class DeliveryAttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    delivery_id: UUID
    attempt_number: int
    started_at: datetime
    completed_at: datetime
    response_status: int | None
    response_body_preview: str | None
    error_type: str | None
    error_message: str | None
    latency_ms: int


class DeliveryResponse(DeliverySummary):
    event_id: UUID
    attempts: list[DeliveryAttemptResponse] = Field(default_factory=list)
