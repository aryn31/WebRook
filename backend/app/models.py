from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.ids import new_id


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    RETRYING = "retrying"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"


def _now_col(**kw: Any) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), **kw)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("usr"))
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    # Per-account overrides of the ingestion limits in settings (NULL = use the default, 0 = unlimited).
    event_rate_limit_per_minute: Mapped[int | None] = mapped_column(Integer)
    daily_event_quota: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _now_col()
    # NULL until the person enters the code emailed to them. Unverified users can only verify or log out.
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Email me when an endpoint in an account I own or administer keeps failing (and when it recovers).
    failure_alerts: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class EmailCode(Base):
    """A short code emailed to a user. Only a keyed hash is stored. One open code per user and purpose."""

    __tablename__ = "email_codes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ecd"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(32))
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _now_col()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ses"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # The account this session is working in: NULL for the user's own account, or a team the user belongs to.
    account_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = _now_col()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Shown on the Security page so people can recognise their devices. Updated at most every few minutes.
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(lazy="joined", foreign_keys=[user_id])


class AccountMember(Base):
    """A user who works in someone else's account (a team). The account owner is implicit and not listed here.

    An account is identified by its owner's user ID, which is the ``user_id`` on all of the account's data.
    """

    __tablename__ = "account_members"

    account_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16))  # admin, developer or viewer
    invited_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _now_col()

    user: Mapped[User] = relationship(lazy="joined", foreign_keys=[user_id])

    __table_args__ = (Index("ix_account_members_user_id", "user_id"),)


class AccountInvite(Base):
    """An invitation to join an account. Only a hash of the token is stored; the link is shown once."""

    __tablename__ = "account_invites"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("inv"))
    account_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _now_col()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("key"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(32), unique=True)
    key_hash: Mapped[str] = mapped_column(String(64))
    # What the key may do (see app/permissions.py). NULL means every API scope (keys made before scopes existed).
    scopes: Mapped[list[str] | None] = mapped_column(JSONB)
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _now_col()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(lazy="joined", foreign_keys=[user_id])


class Endpoint(Base):
    __tablename__ = "endpoints"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ep"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    secret_encrypted: Mapped[str] = mapped_column(Text)
    # After a rotation, the old secret keeps signing (as a second signature) until this time.
    previous_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    previous_secret_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Attempts per delivery for new deliveries to this endpoint, including the first.
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    # Seconds to wait before each retry: [after attempt 1, after attempt 2, ...]. The last value repeats.
    # NULL uses the default exponential backoff.
    retry_schedule: Mapped[list[int] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _now_col()
    updated_at: Mapped[datetime] = _now_col(onupdate=func.now())
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Failure alerts (app/alerts.py): failed attempts in a row, when this run of failures started, and when the
    # "endpoint is failing" email went out. All reset by the next successful attempt.
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failing_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alert_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Last receiver security check (app/security_check.py): verdict, summary, time and each test request's result.
    security_check: Mapped[dict | None] = mapped_column(JSONB)

    subscriptions: Mapped[list["EndpointSubscription"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="EndpointSubscription.event_type"
    )

    @property
    def event_types(self) -> list[str]:
        return [s.event_type for s in self.subscriptions]


class EndpointSubscription(Base):
    __tablename__ = "endpoint_subscriptions"

    endpoint_id: Mapped[str] = mapped_column(ForeignKey("endpoints.id", ondelete="CASCADE"), primary_key=True)
    # Exact event type, "*" for every event type, or a pattern like "order.*" (any type starting with "order.").
    event_type: Mapped[str] = mapped_column(String(100), primary_key=True)

    __table_args__ = (Index("ix_endpoint_subscriptions_event_type", "event_type"),)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("evt"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (
        Index("ix_events_user_id_id", "user_id", "id"),
        Index("ix_events_user_id_created_at", "user_id", "created_at"),
        Index("ix_events_created_at", "created_at"),  # retention cleanup
    )


class Delivery(Base):
    __tablename__ = "deliveries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("dlv"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    endpoint_id: Mapped[str] = mapped_column(ForeignKey("endpoints.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16), default=DeliveryStatus.PENDING)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # While processing: the worker's lease. If it expires, the sweeper reclaims the delivery.
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Last time the sweeper put this delivery on the queue. Stops it re-queueing the same work every tick.
    enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # attempt_count when the current run of attempts began (0, or the count at the last replay).
    # Retry backoff and the "gave up after N attempts" message count from here.
    retry_base_attempt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    replay_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_replayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now_col()
    updated_at: Mapped[datetime] = _now_col(onupdate=func.now())

    event: Mapped[Event] = relationship(lazy="joined", innerjoin=True)
    endpoint: Mapped[Endpoint] = relationship(lazy="joined", innerjoin=True)

    __table_args__ = (
        UniqueConstraint("event_id", "endpoint_id", name="uq_deliveries_event_endpoint"),
        Index("ix_deliveries_user_id_id", "user_id", "id"),
        Index("ix_deliveries_endpoint_id_id", "endpoint_id", "id"),
        Index("ix_deliveries_user_id_created_at", "user_id", "created_at"),
        # Sweeper scans: due work and expired leases.
        Index(
            "ix_deliveries_due",
            "next_attempt_at",
            postgresql_where="status IN ('pending', 'retrying')",
        ),
        Index("ix_deliveries_leases", "locked_until", postgresql_where="status = 'processing'"),
    )


class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("att"))
    delivery_id: Mapped[str] = mapped_column(ForeignKey("deliveries.id", ondelete="CASCADE"))
    attempt_number: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    success: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index("ix_delivery_attempts_delivery_id", "delivery_id", "attempt_number"),
        Index("ix_delivery_attempts_completed_at", "completed_at"),  # recent-activity metrics
    )


class IdempotencyKey(Base):
    """Remembers an ``Idempotency-Key`` sent to ``POST /v1/events`` so a retried request returns the same event."""

    __tablename__ = "idempotency_keys"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(255))
    # SHA-256 of the canonical request (event type + data). A different request with the same key is a conflict.
    request_hash: Mapped[str] = mapped_column(String(64))
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = _now_col()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        PrimaryKeyConstraint("user_id", "key", name="pk_idempotency_keys"),
        Index("ix_idempotency_keys_expires_at", "expires_at"),
    )


class OutboxMessage(Base):
    """A queue message waiting to be published ("deliver dlv_...").

    Written in the same transaction as the work it announces, then published to Redis by the API right after
    commit or by the outbox publisher. If Redis is down, nothing is lost: the row waits here.
    """

    __tablename__ = "outbox"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("obx"))
    delivery_id: Mapped[str] = mapped_column(ForeignKey("deliveries.id", ondelete="CASCADE"))
    # Not published before this time (used for scheduled retries).
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now_col()
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_outbox_unpublished", "available_at", postgresql_where="published_at IS NULL"),
        Index("ix_outbox_delivery_id", "delivery_id"),
    )


class DeliveryReplay(Base):
    """One manual replay of a delivery. Attempts from ``first_attempt_number`` on belong to it."""

    __tablename__ = "delivery_replays"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("rpl"))
    delivery_id: Mapped[str] = mapped_column(ForeignKey("deliveries.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    actor_type: Mapped[str] = mapped_column(String(16))  # "session" or "api_key"
    api_key_id: Mapped[str | None] = mapped_column(ForeignKey("api_keys.id", ondelete="SET NULL"))
    previous_status: Mapped[str] = mapped_column(String(16))
    first_attempt_number: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_delivery_replays_delivery_id", "delivery_id", "id"),)


class AuditLog(Base):
    """Important account actions: key and endpoint changes, secret access, replays, logins."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("aud"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    actor_type: Mapped[str] = mapped_column(String(16))  # "session" or "api_key"
    api_key_id: Mapped[str | None] = mapped_column(ForeignKey("api_keys.id", ondelete="SET NULL"))
    # The person who did it (for API keys, the key's creator). user_id above is the account it happened in.
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str | None] = mapped_column(String(32))
    resource_id: Mapped[str | None] = mapped_column(String(32))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (
        Index("ix_audit_logs_user_id_id", "user_id", "id"),
        Index("ix_audit_logs_resource_id", "resource_id"),
        Index("ix_audit_logs_created_at", "created_at"),  # retention cleanup
    )
