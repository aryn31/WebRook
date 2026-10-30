import re
from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

T = TypeVar("T")

EVENT_TYPE_RE = re.compile(r"^[A-Za-z0-9_\-]+(\.[A-Za-z0-9_\-]+)*$")


def validate_event_type(value: str, allow_wildcard: bool = False) -> str:
    value = value.strip()
    if allow_wildcard and value == "*":
        return value
    if not 1 <= len(value) <= 100 or not EVENT_TYPE_RE.match(value):
        raise ValueError(
            "Event types use letters, digits, '_' or '-' in dot-separated parts, e.g. 'order.created'."
        )
    return value


class Page(BaseModel, Generic[T]):
    data: list[T]
    next_cursor: str | None = None


class ListOf(BaseModel, Generic[T]):
    data: list[T]


# --- Auth --------------------------------------------------------------------

class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class RegisterIn(Credentials):
    password: str = Field(min_length=10, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    created_at: datetime


class UserEnvelope(BaseModel):
    user: UserOut


# --- API keys ----------------------------------------------------------------

class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyEnvelope(BaseModel):
    api_key: ApiKeyOut


class ApiKeyCreated(ApiKeyEnvelope):
    key: str


# --- Endpoints ---------------------------------------------------------------

def _clean_event_types(values: list[str]) -> list[str]:
    cleaned = sorted({validate_event_type(v, allow_wildcard=True) for v in values})
    if not cleaned:
        raise ValueError("Subscribe to at least one event type (use '*' for all).")
    if len(cleaned) > 100:
        raise ValueError("At most 100 event types per endpoint.")
    return cleaned


class EndpointIn(BaseModel):
    url: str = Field(max_length=2048)
    description: str | None = Field(default=None, max_length=500)
    event_types: list[str]
    enabled: bool = True

    @field_validator("event_types")
    @classmethod
    def _v_types(cls, v: list[str]) -> list[str]:
        return _clean_event_types(v)


class EndpointPatch(BaseModel):
    url: str | None = Field(default=None, max_length=2048)
    description: str | None = Field(default=None, max_length=500)
    event_types: list[str] | None = None
    enabled: bool | None = None

    @field_validator("event_types")
    @classmethod
    def _v_types(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _clean_event_types(v)


class EndpointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    url: str
    description: str | None
    enabled: bool
    event_types: list[str]
    created_at: datetime
    updated_at: datetime


class EndpointCreated(EndpointOut):
    signing_secret: str


class SigningSecret(BaseModel):
    signing_secret: str


# --- Events ------------------------------------------------------------------

class EventIn(BaseModel):
    event_type: str
    data: dict[str, Any]

    @field_validator("event_type")
    @classmethod
    def _v_type(cls, v: str) -> str:
        return validate_event_type(v)


class EventAccepted(BaseModel):
    event_id: str
    status: Literal["accepted"] = "accepted"
    created_at: datetime
    delivery_count: int


class DeliveryCounts(BaseModel):
    total: int = 0
    pending: int = 0
    processing: int = 0
    retrying: int = 0
    delivered: int = 0
    failed: int = 0
    cancelled: int = 0


class EventSummary(BaseModel):
    id: str
    event_type: str
    created_at: datetime
    deliveries: DeliveryCounts


class EventOut(EventSummary):
    data: dict[str, Any]


# --- Deliveries --------------------------------------------------------------

class DeliveryOut(BaseModel):
    id: str
    event_id: str
    event_type: str
    endpoint_id: str
    endpoint_url: str
    status: str
    attempt_count: int
    max_attempts: int
    next_attempt_at: datetime | None
    last_status_code: int | None
    last_error: str | None
    delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    attempt_number: int
    started_at: datetime
    completed_at: datetime | None
    duration_ms: int | None
    response_status: int | None
    response_body: str | None
    error: str | None
    success: bool


# --- Stats -------------------------------------------------------------------

class StatsBucket(BaseModel):
    bucket: datetime
    events: int
    delivered: int
    failed: int


class StatsOut(BaseModel):
    range: Literal["24h", "7d", "30d"]
    events_total: int
    deliveries_total: int
    deliveries_by_status: dict[str, int]
    series: list[StatsBucket]
