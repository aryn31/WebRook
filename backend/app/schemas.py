import re
from datetime import UTC, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field, field_validator

T = TypeVar("T")

EVENT_TYPE_RE = re.compile(r"^[A-Za-z0-9_\-]+(\.[A-Za-z0-9_\-]+)*$")


def validate_event_type(value: str, allow_wildcard: bool = False) -> str:
    """An event type. With ``allow_wildcard`` (subscriptions), also "*" or a pattern like "order.*"."""
    value = value.strip()
    if allow_wildcard:
        if value == "*":
            return value
        if value.endswith(".*"):
            prefix = value[:-2]
            if len(value) <= 100 and EVENT_TYPE_RE.match(prefix):
                return value
            raise ValueError(
                "Patterns end in '.*' after an event type prefix, e.g. 'order.*'. '*' is only allowed there."
            )
    if not 1 <= len(value) <= 100 or not EVENT_TYPE_RE.match(value):
        raise ValueError(
            "Event types use letters, digits, '_' or '-' in dot-separated parts, e.g. 'order.created'."
            + (" Subscriptions can also use '*' or a pattern like 'order.*'." if allow_wildcard else "")
        )
    return value


def matching_subscriptions(event_type: str) -> list[str]:
    """Every subscription value that matches ``event_type``.

    "order.item.added" is matched by itself, "*", "order.*" and "order.item.*". Listing them lets ingestion
    find subscribers with one indexed IN query.
    """
    parts = event_type.split(".")
    return [event_type, "*", *(".".join(parts[:i]) + ".*" for i in range(1, len(parts)))]


def subscription_matches(pattern: str, event_type: str) -> bool:
    return pattern in matching_subscriptions(event_type)


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
    email_verified_at: datetime | None = Field(default=None, exclude=True)
    # Email me when an endpoint keeps failing (only sent for accounts I own or administer).
    failure_alerts: bool = True

    @computed_field
    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None


class AccountOut(BaseModel):
    """An account the user can work in: their own, or a team they were invited to."""

    id: str
    # Accounts are named after their owner.
    owner_email: str
    role: Literal["owner", "admin", "developer", "viewer"]
    personal: bool


class MeOut(BaseModel):
    user: UserOut
    # The account this session is working in, the user's role there, and what that role allows.
    account: AccountOut
    permissions: list[str]
    accounts: list[AccountOut]


class UserEnvelope(BaseModel):
    user: UserOut


class RegisterOut(UserEnvelope):
    # False when the verification email couldn't be sent; the dashboard offers to send it again.
    verification_email_sent: bool


class VerifyEmailIn(BaseModel):
    code: str = Field(min_length=1, max_length=16)


class VerificationSentOut(BaseModel):
    sent_to: str
    resend_after_seconds: int


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    topic: Literal["question", "support", "sales", "bug", "other"] = "question"
    message: str = Field(min_length=10, max_length=5000)
    # Hidden from people; bots tend to fill every field. Anything here means the message is quietly dropped.
    website: str = Field(default="", max_length=200)


class ContactOut(BaseModel):
    message: str


class PreferencesIn(BaseModel):
    failure_alerts: bool


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ForgotPasswordOut(BaseModel):
    # Always the same answer, whether or not an account exists, so the form can't be used to find accounts.
    message: str
    resend_after_seconds: int


class ResetPasswordIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=1, max_length=16)
    new_password: str = Field(min_length=10, max_length=256)


class SwitchAccountIn(BaseModel):
    account_id: str = Field(max_length=32)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=10, max_length=256)


class PasswordChangeOut(BaseModel):
    signed_out_sessions: int


class SessionOut(BaseModel):
    id: str
    created_at: datetime
    last_seen_at: datetime | None
    expires_at: datetime
    ip_address: str | None
    user_agent: str | None
    current: bool


class SignedOutOut(BaseModel):
    signed_out_sessions: int


# --- Team --------------------------------------------------------------------

MemberRole = Literal["admin", "developer", "viewer"]


class MemberOut(BaseModel):
    user_id: str
    email: str
    role: Literal["owner", "admin", "developer", "viewer"]
    joined_at: datetime


class MemberPatch(BaseModel):
    role: MemberRole


class InviteIn(BaseModel):
    email: EmailStr
    role: MemberRole = "developer"


class InviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    role: str
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None


class InviteCreated(BaseModel):
    invite: InviteOut
    # Shown once. Share the link with the invitee; they open it while logged in with the invited email.
    token: str
    accept_path: str


class InvitePreview(BaseModel):
    account_owner_email: str
    email: str
    role: str
    expires_at: datetime


# --- API keys ----------------------------------------------------------------

class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] | None = Field(
        default=None,
        description="What the key may do. Default: every scope your role allows. See GET /v1/api-keys/scopes.",
    )

    @field_validator("scopes")
    @classmethod
    def _v_scopes(cls, v: list[str] | None) -> list[str] | None:
        from app.permissions import API_SCOPES

        if v is None:
            return None
        unknown = sorted(set(v) - set(API_SCOPES))
        if unknown:
            raise ValueError(f"Unknown scope(s): {', '.join(unknown)}. Valid: {', '.join(API_SCOPES)}.")
        if not v:
            raise ValueError("Give the key at least one scope.")
        return [s for s in API_SCOPES if s in v]


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    prefix: str
    # Never null in responses: keys made before scopes existed have every scope.
    scopes: list[str]
    created_by_user_id: str | None = None
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyEnvelope(BaseModel):
    api_key: ApiKeyOut


class ApiKeyCreated(ApiKeyEnvelope):
    key: str


class ScopeOut(BaseModel):
    scope: str
    description: str


# --- Endpoints ---------------------------------------------------------------

def _clean_event_types(values: list[str]) -> list[str]:
    cleaned = sorted({validate_event_type(v, allow_wildcard=True) for v in values})
    if not cleaned:
        raise ValueError("Subscribe to at least one event type (use '*' for all, or a pattern like 'order.*').")
    if len(cleaned) > 100:
        raise ValueError("At most 100 event types per endpoint.")
    return cleaned


MaxAttempts = Field(default=None, ge=1, le=10, description="Attempts per delivery, including the first (1-10).")

MAX_SCHEDULE_DELAY = 24 * 3600
RetrySchedule = Field(
    default=None,
    description="Seconds to wait before each retry, e.g. [10, 60, 600]: 10s after the 1st attempt fails, 60s "
    "after the 2nd, then 600s for every later retry. 1-9 values, each 1 second to 24 hours. "
    "Null uses the default exponential backoff.",
)


def _clean_schedule(v: list[int] | None) -> list[int] | None:
    if v is None:
        return None
    if not 1 <= len(v) <= 9:
        raise ValueError("A retry schedule has 1 to 9 delays (one per retry; the last one repeats).")
    if any(not 1 <= d <= MAX_SCHEDULE_DELAY for d in v):
        raise ValueError("Each retry delay must be between 1 second and 24 hours (86400 seconds).")
    return v


class EndpointIn(BaseModel):
    url: str = Field(max_length=2048)
    description: str | None = Field(default=None, max_length=500)
    event_types: list[str]
    enabled: bool = True
    max_attempts: int | None = MaxAttempts
    retry_schedule: list[int] | None = RetrySchedule

    @field_validator("event_types")
    @classmethod
    def _v_types(cls, v: list[str]) -> list[str]:
        return _clean_event_types(v)

    @field_validator("retry_schedule")
    @classmethod
    def _v_schedule(cls, v: list[int] | None) -> list[int] | None:
        return _clean_schedule(v)


class EndpointPatch(BaseModel):
    url: str | None = Field(default=None, max_length=2048)
    description: str | None = Field(default=None, max_length=500)
    event_types: list[str] | None = None
    enabled: bool | None = None
    max_attempts: int | None = MaxAttempts
    # Send null to go back to the default backoff.
    retry_schedule: list[int] | None = RetrySchedule

    @field_validator("event_types")
    @classmethod
    def _v_types(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _clean_event_types(v)

    @field_validator("retry_schedule")
    @classmethod
    def _v_schedule(cls, v: list[int] | None) -> list[int] | None:
        return _clean_schedule(v)


class EndpointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    url: str
    description: str | None
    enabled: bool
    event_types: list[str]
    max_attempts: int
    retry_schedule: list[int] | None = None
    # When the old secret stops signing after a rotation; null when there's no grace period running.
    previous_secret_expires_at: datetime | None = None
    # When the "endpoint is failing" email went out for the current run of failures; null once it recovers.
    alert_sent_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("previous_secret_expires_at")
    @classmethod
    def _only_if_active(cls, v: datetime | None) -> datetime | None:
        return v if v is not None and v > datetime.now(UTC) else None


class EndpointHealth(BaseModel):
    """Delivery attempts to this endpoint in the last 24 hours."""

    # idle: no attempts. healthy: 95%+ succeeded. failing: the last attempt failed and under half succeeded.
    # degraded: anything in between.
    state: Literal["idle", "healthy", "degraded", "failing"]
    attempts: int
    successes: int
    success_rate: float | None  # 0-1; null when there were no attempts
    last_attempt_at: datetime | None
    last_success: bool | None
    last_status_code: int | None
    last_error: str | None


class EndpointWithHealth(EndpointOut):
    health: EndpointHealth


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
    # The person: the logged-in user, or the API key's creator. Null for older entries.
    user_id: str | None = None
    email: str | None = None


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


class BulkReplayIn(BaseModel):
    endpoint_id: str | None = Field(default=None, max_length=32)
    event_type: str | None = Field(default=None, max_length=100)
    statuses: list[Literal["failed", "cancelled"]] = Field(default_factory=lambda: ["failed"], min_length=1)
    created_after: datetime | None = None
    created_before: datetime | None = None
    limit: int = Field(default=100, ge=1, le=500, description="Most deliveries to replay in this request.")
    dry_run: bool = Field(default=False, description="Only report what would be replayed.")


class BulkReplayOut(BaseModel):
    # Deliveries that matched the filters in this batch (at most `limit`).
    matched: int
    # Replayed (or, for a dry run, would be replayed).
    replayed: list[str]
    skipped: list[ReplaySkipped]
    # More matching deliveries exist beyond this batch. Call again to continue.
    has_more: bool
    dry_run: bool


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


class LatencyOut(BaseModel):
    p50: float
    p95: float


class StatsOut(BaseModel):
    range: Literal["24h", "7d", "30d"]
    events_total: int
    deliveries_total: int
    deliveries_by_status: dict[str, int]
    # How long endpoints took to respond, over attempts in the range. Null when there were none.
    latency_ms: LatencyOut | None
    series: list[StatsBucket]


class UsageWindow(BaseModel):
    limit: int | None  # null = unlimited
    used: int
    remaining: int | None
    resets_in_seconds: int


class UsageOut(BaseModel):
    # New events today (UTC). Counts toward the daily quota.
    events_today: UsageWindow
    # Ingestion requests this minute. Counts toward the rate limit.
    requests_this_minute: UsageWindow
