"""Operational state of the delivery pipeline, read straight from Postgres and Redis.

Used by GET /metrics (Prometheus) and by the monitor task, which logs an alert when work is stuck. Reading the
database means the numbers are right no matter how many API or worker processes there are.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Delivery, DeliveryAttempt, DeliveryStatus, OutboxMessage
from app.ratelimit import get_redis

log = logging.getLogger("hookflow.monitor")

HEARTBEAT_KEY = "hookflow:heartbeat:worker"
RECENT = timedelta(minutes=5)
QUEUED_STATUSES = (DeliveryStatus.PENDING, DeliveryStatus.RETRYING, DeliveryStatus.PROCESSING)


def beat_heartbeat() -> None:
    """Called by the worker's scheduled tasks. Its age shows whether the worker and scheduler are running."""
    try:
        get_redis().set(HEARTBEAT_KEY, time.time(), ex=24 * 3600)
    except redis.RedisError:
        pass


def worker_silence_seconds() -> float | None:
    """Seconds since the worker last ran a scheduled task. None if unknown (never seen, or Redis down)."""
    try:
        value = get_redis().get(HEARTBEAT_KEY)
    except redis.RedisError:
        return None
    return max(time.time() - float(value), 0.0) if value else None


@dataclass
class Snapshot:
    deliveries_by_status: dict[str, int] = field(default_factory=dict)  # queued work only
    oldest_due_seconds: float = 0.0  # how long the longest-waiting due delivery has waited
    outbox_unpublished: int = 0
    outbox_oldest_due_seconds: float = 0.0
    recent_attempts: dict[str, int] = field(default_factory=dict)  # last 5 minutes: success / failure
    recent_latency_ms: dict[str, float] = field(default_factory=dict)  # last 5 minutes: p50 / p95 / p99
    worker_silence_seconds: float | None = None


def _age(now: datetime, ts: datetime | None) -> float:
    return max((now - ts).total_seconds(), 0.0) if ts else 0.0


def snapshot(db: Session) -> Snapshot:
    now = datetime.now(UTC)
    snap = Snapshot()

    rows = db.execute(
        select(Delivery.status, func.count()).where(Delivery.status.in_(QUEUED_STATUSES)).group_by(Delivery.status)
    ).all()
    snap.deliveries_by_status = {str(s): 0 for s in QUEUED_STATUSES} | {status: n for status, n in rows}

    oldest_due = db.scalar(
        select(func.min(Delivery.next_attempt_at)).where(
            Delivery.status.in_((DeliveryStatus.PENDING, DeliveryStatus.RETRYING)), Delivery.next_attempt_at <= now
        )
    )
    snap.oldest_due_seconds = _age(now, oldest_due)

    count, oldest = db.execute(
        select(func.count(), func.min(OutboxMessage.available_at)).where(OutboxMessage.published_at.is_(None))
    ).one()
    snap.outbox_unpublished = count
    snap.outbox_oldest_due_seconds = _age(now, oldest) if oldest and oldest <= now else 0.0

    since = now - RECENT
    rows = db.execute(
        select(DeliveryAttempt.success, func.count())
        .where(DeliveryAttempt.completed_at >= since)
        .group_by(DeliveryAttempt.success)
    ).all()
    snap.recent_attempts = {"success": 0, "failure": 0} | {("success" if ok else "failure"): n for ok, n in rows}

    p50, p95, p99 = db.execute(
        select(
            func.percentile_cont(0.5).within_group(DeliveryAttempt.duration_ms),
            func.percentile_cont(0.95).within_group(DeliveryAttempt.duration_ms),
            func.percentile_cont(0.99).within_group(DeliveryAttempt.duration_ms),
        ).where(DeliveryAttempt.completed_at >= since, DeliveryAttempt.duration_ms.is_not(None))
    ).one()
    snap.recent_latency_ms = {q: float(v) for q, v in (("p50", p50), ("p95", p95), ("p99", p99)) if v is not None}

    snap.worker_silence_seconds = worker_silence_seconds()
    return snap


# --- Alerts -----------------------------------------------------------------------------------------------

ALERT_REPEAT_SECONDS = 15 * 60


def _alert(name: str, firing: bool, message: str, **details) -> bool:
    """Log an ERROR when an alert starts (and every 15 minutes while it lasts), and an INFO when it clears."""
    key = f"hookflow:alert:{name}"
    try:
        r = get_redis()
        if firing:
            if r.set(key, "1", nx=True, ex=ALERT_REPEAT_SECONDS):
                log.error("ALERT %s: %s", name, message, extra={"alert": name, **details})
            return True
        if r.delete(key):
            log.info("Alert resolved: %s", name, extra={"alert": name, "resolved": True})
    except redis.RedisError:
        if firing:  # can't de-duplicate, so log every time rather than stay quiet
            log.error("ALERT %s: %s", name, message, extra={"alert": name, **details})
    return firing


def check_alerts(snap: Snapshot) -> list[str]:
    """Evaluate the operator alerts. Returns the names of those firing."""
    s = get_settings()
    firing = []
    if _alert("delivery_queue_delayed", snap.oldest_due_seconds > s.alert_queue_delay_seconds,
              f"A due delivery has waited {snap.oldest_due_seconds:.0f}s to be sent. Check that workers are running.",
              oldest_due_seconds=round(snap.oldest_due_seconds)):
        firing.append("delivery_queue_delayed")
    if _alert("outbox_backlog", snap.outbox_oldest_due_seconds > s.alert_queue_delay_seconds,
              f"Queue messages have waited {snap.outbox_oldest_due_seconds:.0f}s to be published. "
              "Check Redis and the scheduler (beat).",
              outbox_unpublished=snap.outbox_unpublished):
        firing.append("outbox_backlog")
    return firing
