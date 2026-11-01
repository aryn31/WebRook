import re
from datetime import UTC, datetime
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


MaxAttempts = Field(default=None, ge=1, le=10, description="Attempts per delivery, including the first (1-10).")


class EndpointIn(BaseModel):
    url: str = Field(max_length=2048)
    description: str | None = Field(default=None, max_length=500)
    event_types: list[str]
    enabled: bool = True
    max_attempts: int | None = MaxAttempts

    @field_validator("event_types")
    @classmethod
    def _v_types(cls, v: list[str]) -> list[str]:
        return _clean_event_types(v)


class EndpointPatch(BaseModel):
    url: str | None = Field(default=None, max_length=2048)
    description: str | None = Field(default=None, max_length=500)
    event_types: list[str] | None = None
    enabled: bool | None = None
    max_attempts: int | None = MaxAttempts

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
    max_attempts: int
    # When the old secret stops signing after a rotation; null when there's no grace period running.
    previous_secret_expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("previous_secret_expires_at")
    @classmethod
    def _only_if_active(cls, v: datetime | None) -> datetime | None:
        return v if v is not None and v > datetime.now(UTC) else None


class EndpointCreated(EndpointOut):
    signing_secret: str


class SigningSecret(BaseModel):
    signing_secret: str
    # Set during a rotation grace period: the old secret also signs requests until then.
    previous_secret_expires_at: datetime | None = None


class RotateSecretIn(BaseModel):
    grace_period_seconds: int | None = Field(
        default=None, ge=0, le=7 * 24 * 3600,
        description="How long the old secret keeps signing too (0 to 7 days). Defaults to 24 hours.",
    )


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
    idempotency_key: str | None = None


# --- Deliveries --------------------------------------------------------------

class DeliveryOut(BaseModel):
    id: str
    event_id: str
    event_type: str
    endpoint_id: str
    endpoint_url: str
    status: str
    # Totals over the delivery's whole life (they keep growing with each manual replay).
    attempt_count: int
    max_attempts: int
    # The same, counted from the last manual replay (or creation). This is what the dashboard shows.
    run_attempt_count: int
    run_max_attempts: int
    next_attempt_at: datetime | None
    last_status_code: int | None
    last_error: str | None
    delivered_at: datetime | None
    replay_count: int
    last_replayed_at: datetime | None
    # True when POST /v1/deliveries/{id}/replay would be accepted right now.
    replayable: bool
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


class Actor(BaseModel):
    type: Literal["session", "api_key"]
    api_key_id: str | None = None


class ReplayOut(BaseModel):
    id: str
    delivery_id: str
    previous_status: str
    first_attempt_number: int
    requested_by: Actor
    created_at: datetime


class DeliveryReplayed(BaseModel):
    replay: ReplayOut
    delivery: "DeliveryOut"


class ReplaySkipped(BaseModel):
    delivery_id: str
    reason: str


class EventReplayIn(BaseModel):
    endpoint_ids: list[str] | None = Field(
        default=None, max_length=100, description="Only replay deliveries to these endpoints. Default: all."
    )


class EventReplayed(BaseModel):
    replayed: list[DeliveryReplayed]
    skipped: list[ReplaySkipped]


# --- Audit log ---------------------------------------------------------------

class AuditLogOut(BaseModel):
    id: str
    action: str
    actor: Actor
    resource_type: str | None
    resource_id: str | None
    details: dict[str, Any] | None
    ip_address: str | None
    created_at: datetime


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
