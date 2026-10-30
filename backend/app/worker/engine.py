"""Delivery engine.

Postgres is the source of truth for delivery work; Redis/Celery only carries "go look at delivery X" messages.

- ``process_delivery`` atomically claims one due delivery (a lease), sends it, and records the outcome.
- ``sweep`` runs every few seconds. It re-queues due work (new deliveries whose queue message was lost,
  and retries whose time has come) and reclaims deliveries whose worker died mid-attempt.

Because a worker can die after the destination got the request but before the result was saved,
delivery is at-least-once. The event ID stays the same so receivers can de-duplicate.
"""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import or_, select, update
from sqlalchemy.orm import lazyload

from app.config import get_settings
from app.db import SessionLocal
from app.models import Delivery, DeliveryAttempt, DeliveryStatus
from app.security import decrypt_secret
from app.signing import sign
from app.urlguard import UnsafeDestination, check_destination
from app.worker.retry import is_retryable_status, retry_delay_seconds

log = logging.getLogger("hookflow.worker")

DUE_STATUSES = (DeliveryStatus.PENDING, DeliveryStatus.RETRYING)
REQUEUE_AFTER = timedelta(seconds=60)


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
    try:
        check_destination(url)
    except UnsafeDestination as exc:
        return Outcome(success=False, retryable=False, error=str(exc))

    timeout = httpx.Timeout(s.delivery_timeout_seconds, connect=s.delivery_connect_timeout_seconds)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
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


def process_delivery(delivery_id: str) -> str:
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

        secret = decrypt_secret(endpoint.secret_encrypted)
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
        "HookFlow-Signature": sign(secret, timestamp, body),
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
        max_attempts = db.scalar(select(Delivery.max_attempts).where(Delivery.id == delivery_id))
        values: dict = {"locked_until": None, "last_status_code": o.status_code}
        if o.success:
            values |= {"status": DeliveryStatus.DELIVERED, "delivered_at": now, "last_error": None}
        elif o.retryable and attempt_number < (max_attempts or 0):
            delay = retry_delay_seconds(attempt_number, o.retry_after)
            values |= {
                "status": DeliveryStatus.RETRYING,
                "next_attempt_at": now + timedelta(seconds=delay),
                "enqueued_at": None,
                "last_error": o.error,
            }
        else:
            error = o.error or "Delivery failed."
            if o.retryable:
                error += f" Gave up after {attempt_number} attempts."
            values |= {"status": DeliveryStatus.FAILED, "last_error": error}

        # Only apply if we still hold the lease. If the sweeper already reclaimed it, keep the attempt
        # record (the request really happened) but leave the delivery state to whoever owns it now.
        result = db.execute(
            update(Delivery)
            .where(Delivery.id == delivery_id, Delivery.status == DeliveryStatus.PROCESSING,
                   Delivery.attempt_count == attempt_number)
            .values(**values)
        )
        if result.rowcount == 0:
            log.warning("Lease lost before result was recorded", extra={"delivery_id": delivery_id})
        db.commit()
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


def sweep(enqueue: Callable[[str], object], batch_size: int = 500) -> dict[str, int]:
    now = _now()
    reclaimed = 0
    with SessionLocal() as db:
        # 1. Reclaim deliveries whose worker lease expired (worker crashed or hung).
        stuck = db.scalars(
            select(Delivery)
            .options(lazyload("*"))
            .where(Delivery.status == DeliveryStatus.PROCESSING, Delivery.locked_until < now)
            .limit(batch_size)
            .with_for_update(skip_locked=True, of=Delivery)
        ).all()
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
                d.last_error = f"Worker stopped during the final attempt. Gave up after {d.attempt_count} attempts."
            else:
                d.status = DeliveryStatus.RETRYING
                d.next_attempt_at = now
                d.last_error = "Worker stopped during the attempt; retrying."
            reclaimed += 1
        db.commit()

        # 2. Queue due work that isn't already queued (or whose queue message was lost).
        due_ids = db.scalars(
            select(Delivery.id)
            .where(
                Delivery.status.in_(DUE_STATUSES),
                Delivery.next_attempt_at <= now,
                or_(Delivery.enqueued_at.is_(None), Delivery.enqueued_at < now - REQUEUE_AFTER),
            )
            .order_by(Delivery.next_attempt_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        ).all()
        if due_ids:
            db.execute(update(Delivery).where(Delivery.id.in_(due_ids)).values(enqueued_at=now))
        db.commit()

    queued = 0
    for delivery_id in due_ids:
        try:
            enqueue(delivery_id)
            queued += 1
        except Exception:  # broker down: the next sweep after REQUEUE_AFTER will try again
            log.exception("Failed to enqueue delivery", extra={"delivery_id": delivery_id})
            break
    if reclaimed or queued:
        log.info("sweep", extra={"reclaimed": reclaimed, "queued": queued})
    return {"reclaimed": reclaimed, "queued": queued}
