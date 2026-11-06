"""Delivery engine.

Postgres is the source of truth for delivery work; Redis/Celery only carries "go look at delivery X" messages.

- ``process_delivery`` atomically claims one due delivery (a lease), sends it, and records the outcome.
  A scheduled retry is written to the outbox in the same transaction as the result.
- ``sweep`` runs every few seconds. It reclaims deliveries whose worker died mid-attempt, and re-queues due
  work whose queue message was published but then lost (e.g. Redis restarted without persistence).

All queue messages go through the transactional outbox (app/outbox.py).

Because a worker can die after the destination got the request but before the result was saved,
delivery is at-least-once. The event ID stays the same so receivers can de-duplicate.
"""

import json
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import delete, exists, or_, select, tuple_, update
from sqlalchemy.orm import lazyload

from app import alerts, outbox
from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    AuditLog, Delivery, DeliveryAttempt, DeliveryStatus, Endpoint, Event, IdempotencyKey, OutboxMessage,
)
from app.security import decrypt_secret
from app.signing import sign
from app.worker import concurrency
from app.urlguard import GuardedTransport, UnresolvableHost, UnsafeDestination
from app.worker.retry import is_retryable_status, retry_delay_seconds

log = logging.getLogger("hookflow.worker")

DUE_STATUSES = (DeliveryStatus.PENDING, DeliveryStatus.RETRYING)
REQUEUE_AFTER = timedelta(seconds=60)
# Published outbox messages are kept this long (for debugging), then deleted by the sweeper.
OUTBOX_KEEP = timedelta(days=1)


@dataclass
class Outcome:
    success: bool
    retryable: bool
    status_code: int | None = None
    error: str | None = None
    response_body: str | None = None
    retry_after: str | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def build_body(event_id: str, event_type: str, created_at: datetime, data: dict) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "type": event_type,
            "created_at": created_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "data": data,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


def send(url: str, body: bytes, headers: dict[str, str]) -> Outcome:
    s = get_settings()
    timeout = httpx.Timeout(s.delivery_timeout_seconds, connect=s.delivery_connect_timeout_seconds)
    try:
        # The transport checks every address it connects to (see app/urlguard.py).
        with httpx.Client(transport=GuardedTransport(), timeout=timeout, follow_redirects=False,
                          trust_env=False) as client:
            with client.stream("POST", url, content=body, headers=headers) as resp:
                chunks, size = [], 0
                for chunk in resp.iter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= s.response_body_max_bytes:
                        break
                text = b"".join(chunks)[: s.response_body_max_bytes].decode("utf-8", errors="replace")
                code = resp.status_code
                retry_after = resp.headers.get("retry-after")
    except UnsafeDestination as exc:
        return Outcome(False, False, error=str(exc))
    except UnresolvableHost as exc:
        return Outcome(False, True, error=str(exc))
    except httpx.TimeoutException:
        return Outcome(False, True, error=f"Destination did not respond within {s.delivery_timeout_seconds:g} seconds.")
    except httpx.ConnectError:
        return Outcome(False, True, error="Could not connect to the destination.")
    except httpx.HTTPError as exc:
        return Outcome(False, True, error=f"Request failed ({type(exc).__name__}).")

    if 200 <= code <= 299:
        return Outcome(True, False, status_code=code, response_body=text)
    if 300 <= code <= 399:
        msg = f"Destination returned HTTP {code} (a redirect). Redirects are not followed; update the endpoint URL."
        return Outcome(False, False, status_code=code, error=msg, response_body=text)
    return Outcome(
        False,
        is_retryable_status(code),
        status_code=code,
        error=f"Destination returned HTTP {code}.",
        response_body=text,
        retry_after=retry_after,
    )


def _claim(delivery_id: str) -> int | None:
    """Atomically move a due delivery to ``processing``. Returns the new attempt number, or None."""
    s = get_settings()
    with SessionLocal() as db:
        row = db.execute(
            update(Delivery)
            .where(
                Delivery.id == delivery_id,
                Delivery.status.in_(DUE_STATUSES),
                Delivery.next_attempt_at <= _now(),
            )
            .values(
                status=DeliveryStatus.PROCESSING,
                attempt_count=Delivery.attempt_count + 1,
                locked_until=_now() + timedelta(seconds=s.delivery_lease_seconds),
                next_attempt_at=None,
            )
            .returning(Delivery.attempt_count)
        ).first()
        db.commit()
        return row[0] if row else None


def _defer(delivery_id: str) -> str:
    """The endpoint is at its concurrency limit: push this delivery back a couple of seconds.

    Doesn't use up an attempt. Only applies if the delivery is still due (another worker may have taken it).
    """
    later = _now() + timedelta(seconds=random.uniform(1.0, 3.0))
    with SessionLocal() as db:
        row = db.execute(
            update(Delivery)
            .where(Delivery.id == delivery_id, Delivery.status.in_(DUE_STATUSES), Delivery.next_attempt_at <= _now())
            .values(next_attempt_at=later, enqueued_at=None)
            .returning(Delivery.id)
        ).first()
        if row:
            outbox.add(db, [delivery_id], available_at=later)
        db.commit()
    return "deferred" if row else "skipped"


def process_delivery(delivery_id: str) -> str:
    """Send one due delivery, keeping within the endpoint's concurrency limit."""
    s = get_settings()
    with SessionLocal() as db:
        endpoint_id = db.scalar(select(Delivery.endpoint_id).where(Delivery.id == delivery_id))
    if endpoint_id is None:
        return "skipped"
    if not concurrency.acquire(endpoint_id, delivery_id, s.endpoint_max_concurrency, s.delivery_lease_seconds):
        return _defer(delivery_id)
    try:
        return _process_claimed(delivery_id)
    finally:
        concurrency.release(endpoint_id, delivery_id)


def _process_claimed(delivery_id: str) -> str:
    attempt_number = _claim(delivery_id)
    if attempt_number is None:
        return "skipped"  # already delivered, claimed by another worker, or not due yet

    with SessionLocal() as db:
        delivery = db.get(Delivery, delivery_id)
        assert delivery is not None
        endpoint, event = delivery.endpoint, delivery.event

        if endpoint.archived_at is not None or not endpoint.enabled:
            delivery.status = DeliveryStatus.CANCELLED
            delivery.attempt_count = attempt_number - 1  # nothing was sent
            delivery.locked_until = None
            delivery.last_error = "Cancelled because the endpoint was disabled or deleted."
            db.commit()
            return "cancelled"

        secrets = [decrypt_secret(endpoint.secret_encrypted)]
        # During a rotation's grace period, also sign with the old secret so receivers that haven't
        # switched yet keep verifying. The header then carries two signatures: "v1=<new>,v1=<old>".
        if endpoint.previous_secret_encrypted and endpoint.previous_secret_expires_at and (
            endpoint.previous_secret_expires_at > _now()
        ):
            secrets.append(decrypt_secret(endpoint.previous_secret_encrypted))
        url = endpoint.url
        body = build_body(event.id, event.event_type, event.created_at, event.payload)

    timestamp = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "HookFlow/1.0",
        "HookFlow-Event-Id": event.id,
        "HookFlow-Event-Type": event.event_type,
        "HookFlow-Delivery-Id": delivery_id,
        "HookFlow-Attempt": str(attempt_number),
        "HookFlow-Timestamp": str(timestamp),
        "HookFlow-Signature": ",".join(sign(secret, timestamp, body) for secret in secrets),
    }

    started = _now()
    t0 = time.perf_counter()
    outcome = send(url, body, headers)
    duration_ms = int((time.perf_counter() - t0) * 1000)
    _record(delivery_id, attempt_number, started, duration_ms, outcome)
    return "delivered" if outcome.success else "failed"


def _record(delivery_id: str, attempt_number: int, started: datetime, duration_ms: int, o: Outcome) -> None:
    now = _now()
    with SessionLocal() as db:
        db.add(
            DeliveryAttempt(
                delivery_id=delivery_id,
                attempt_number=attempt_number,
                started_at=started,
                completed_at=now,
                duration_ms=duration_ms,
                response_status=o.status_code,
                response_body=o.response_body,
                error=o.error,
                success=o.success,
            )
        )
        max_attempts, base, schedule, endpoint_id = db.execute(
            select(Delivery.max_attempts, Delivery.retry_base_attempt, Endpoint.retry_schedule, Endpoint.id)
            .join(Endpoint, Endpoint.id == Delivery.endpoint_id)
            .where(Delivery.id == delivery_id)
        ).one()
        # Attempts in the current run: since creation, or since the last manual replay.
        run_attempt = attempt_number - base
        values: dict = {"locked_until": None, "last_status_code": o.status_code}
        next_at: datetime | None = None
        if o.success:
            values |= {"status": DeliveryStatus.DELIVERED, "delivered_at": now, "last_error": None}
        elif o.retryable and attempt_number < max_attempts:
            next_at = now + timedelta(seconds=retry_delay_seconds(run_attempt, o.retry_after, schedule))
            values |= {
                "status": DeliveryStatus.RETRYING,
                "next_attempt_at": next_at,
                "enqueued_at": None,
                "last_error": o.error,
            }
        else:
            error = o.error or "Delivery failed."
            if o.retryable:
                error += f" Gave up after {run_attempt} attempts."
            values |= {"status": DeliveryStatus.FAILED, "last_error": error}

        # Only apply if we still hold the lease. If the sweeper already reclaimed it, keep the attempt
        # record (the request really happened) but leave the delivery state to whoever owns it now.
        result = db.execute(
            update(Delivery)
            .where(Delivery.id == delivery_id, Delivery.status == DeliveryStatus.PROCESSING,
                   Delivery.attempt_count == attempt_number)
            .values(**values)
        )
        alert: alerts.Pending | None = None
        if result.rowcount == 0:
            log.warning("Lease lost before result was recorded", extra={"delivery_id": delivery_id})
        else:
            if next_at is not None:
                outbox.add(db, [delivery_id], available_at=next_at)
            alert = alerts.on_attempt(db, endpoint_id, o.success, now)
        db.commit()
    if alert is not None:
        alerts.send(alert)
    log.info(
        "delivery attempt",
        extra={
            "delivery_id": delivery_id,
            "attempt": attempt_number,
            "success": o.success,
            "status_code": o.status_code,
            "duration_ms": duration_ms,
            "new_status": values.get("status"),
        },
    )


def sweep(batch_size: int = 500) -> dict[str, int]:
    now = _now()
    with SessionLocal() as db:
        # 1. Reclaim deliveries whose worker lease expired (worker crashed or hung).
        stuck = db.scalars(
            select(Delivery)
            .options(lazyload("*"))
            .where(Delivery.status == DeliveryStatus.PROCESSING, Delivery.locked_until < now)
            .limit(batch_size)
            .with_for_update(skip_locked=True, of=Delivery)
        ).all()
        retry_ids: list[str] = []
        for d in stuck:
            db.add(
                DeliveryAttempt(
                    delivery_id=d.id,
                    attempt_number=d.attempt_count,
                    started_at=d.locked_until - timedelta(seconds=get_settings().delivery_lease_seconds),
                    error="The worker stopped before recording a result. "
                    "The destination may or may not have received this attempt.",
                    success=False,
                )
            )
            d.locked_until = None
            d.enqueued_at = None
            if d.attempt_count >= d.max_attempts:
                d.status = DeliveryStatus.FAILED
                d.last_error = (
                    "Worker stopped during the final attempt. "
                    f"Gave up after {d.attempt_count - d.retry_base_attempt} attempts."
                )
            else:
                d.status = DeliveryStatus.RETRYING
                d.next_attempt_at = now
                d.last_error = "Worker stopped during the attempt; retrying."
                retry_ids.append(d.id)
        outbox.add(db, retry_ids)
        db.commit()

        # 2. Safety net: due work that was published a while ago but never picked up (the message was lost
        #    in Redis) and has no unpublished outbox message waiting. Stage a fresh message for it.
        waiting = exists().where(OutboxMessage.delivery_id == Delivery.id, OutboxMessage.published_at.is_(None))
        lost_ids = db.scalars(
            select(Delivery.id)
            .where(
                Delivery.status.in_(DUE_STATUSES),
                Delivery.next_attempt_at <= now,
                or_(Delivery.enqueued_at.is_(None), Delivery.enqueued_at < now - REQUEUE_AFTER),
                ~waiting,
            )
            .order_by(Delivery.next_attempt_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        ).all()
        if lost_ids:
            outbox.add(db, lost_ids)
            # Counts as queued from now, so the next sweep doesn't stage it again straight away.
            db.execute(update(Delivery).where(Delivery.id.in_(lost_ids)).values(enqueued_at=now))
        db.commit()

        # 3. Housekeeping: old published outbox messages and expired idempotency keys, a batch at a time.
        old_messages = select(OutboxMessage.id).where(OutboxMessage.published_at < now - OUTBOX_KEEP).limit(batch_size)
        cleaned = db.execute(delete(OutboxMessage).where(OutboxMessage.id.in_(old_messages))).rowcount
        expired_keys = (
            select(IdempotencyKey.user_id, IdempotencyKey.key).where(IdempotencyKey.expires_at < now).limit(batch_size)
        )
        cleaned += db.execute(
            delete(IdempotencyKey).where(
                tuple_(IdempotencyKey.user_id, IdempotencyKey.key).in_(expired_keys)
            )
        ).rowcount
        db.commit()

    expired = delete_expired(now, batch_size)
    result = {"reclaimed": len(stuck), "requeued": len(lost_ids), "cleaned": cleaned, "expired": expired}
    if len(stuck) or lost_ids or expired:
        log.info("sweep", extra=result)
    return result


ACTIVE_STATUSES = (DeliveryStatus.PENDING, DeliveryStatus.PROCESSING, DeliveryStatus.RETRYING)


def delete_expired(now: datetime, batch_size: int = 500) -> int:
    """Retention: delete old events and audit entries, a batch at a time.

    Deleting an event also deletes its deliveries, attempts, replays and queue messages (foreign keys cascade).
    Events with a delivery still in progress are kept until it finishes.
    """
    s = get_settings()
    deleted = 0
    with SessionLocal() as db:
        if s.event_retention_days > 0:
            active = exists().where(Delivery.event_id == Event.id, Delivery.status.in_(ACTIVE_STATUSES))
            old_events = (
                select(Event.id)
                .where(Event.created_at < now - timedelta(days=s.event_retention_days), ~active)
                .limit(batch_size)
            )
            deleted += db.execute(delete(Event).where(Event.id.in_(old_events))).rowcount
        if s.audit_log_retention_days > 0:
            old_audit = (
                select(AuditLog.id)
                .where(AuditLog.created_at < now - timedelta(days=s.audit_log_retention_days))
                .limit(batch_size)
            )
            deleted += db.execute(delete(AuditLog).where(AuditLog.id.in_(old_audit))).rowcount
        db.commit()
    return deleted
