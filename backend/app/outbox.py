"""Transactional outbox for queue messages.

Any code that creates delivery work (ingestion, retries, replays, crash recovery) calls ``add`` inside the
same database transaction. The message is therefore saved if and only if the work is saved. Publishing to
Redis happens afterwards:

- ``publish_ids`` right after commit (best effort, so deliveries usually start at once), and
- ``publish_due`` from the outbox publisher every second, which picks up anything not yet published:
  messages whose immediate publish failed, and scheduled retries whose time has come.

A message can be published twice (e.g. the process dies between sending and marking it published).
That's harmless: workers claim deliveries atomically, so a duplicate message does nothing.
"""

import logging
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import queue
from app.db import SessionLocal
from app.ids import new_id
from app.models import Delivery, OutboxMessage

log = logging.getLogger("hookflow.outbox")


def add(db: Session, delivery_ids: Iterable[str], available_at: datetime | None = None) -> list[str]:
    """Stage a queue message per delivery in the caller's transaction. Returns the message IDs."""
    when = available_at or datetime.now(UTC)
    messages = [OutboxMessage(id=new_id("obx"), delivery_id=d, available_at=when) for d in delivery_ids]
    db.add_all(messages)
    return [m.id for m in messages]


def _publish(db: Session, messages: list[OutboxMessage]) -> int:
    now = datetime.now(UTC)
    sent: list[str] = []
    for m in messages:
        try:
            queue.send_delivery(m.delivery_id)
        except Exception as exc:  # broker unreachable: leave the rest for the next run
            m.publish_attempts += 1
            m.last_error = f"{type(exc).__name__}: {exc}"[:500]
            log.warning("Outbox publish failed; will retry", extra={"delivery_id": m.delivery_id})
            break
        m.published_at = now
        sent.append(m.delivery_id)
    if sent:
        db.execute(update(Delivery).where(Delivery.id.in_(sent)).values(enqueued_at=now))
    db.commit()
    return len(sent)


def publish_ids(message_ids: list[str]) -> int:
    """Publish specific messages now. Never raises; anything left unpublished is retried by ``publish_due``."""
    if not message_ids:
        return 0
    try:
        with SessionLocal() as db:
            messages = db.scalars(
                select(OutboxMessage)
                .where(OutboxMessage.id.in_(message_ids), OutboxMessage.published_at.is_(None))
                .with_for_update(skip_locked=True)
            ).all()
            return _publish(db, list(messages))
    except Exception:
        log.exception("Immediate outbox publish failed; the publisher will retry")
        return 0


def publish_due(batch_size: int = 500) -> int:
    """Publish unpublished messages whose time has come. Safe to run from several processes at once."""
    with SessionLocal() as db:
        messages = db.scalars(
            select(OutboxMessage)
            .where(OutboxMessage.published_at.is_(None), OutboxMessage.available_at <= datetime.now(UTC))
            .order_by(OutboxMessage.available_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        ).all()
        published = _publish(db, list(messages))
    if published:
        log.info("outbox published", extra={"published": published})
    return published
