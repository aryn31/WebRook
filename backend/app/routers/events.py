import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Body, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit, outbox
from app.config import get_settings
from app.deps import DB, CurrentPrincipal
from app.errors import ApiError, not_found
from app.ids import new_id
from app.models import Delivery, DeliveryStatus, Endpoint, EndpointSubscription, Event, IdempotencyKey
from app.pagination import Cursor, Limit, paginate
from app.replay import enforce_rate_limit, replay, replay_out, why_not_replayable
from app.routers.deliveries import delivery_out
from app.schemas import (
    DeliveryCounts,
    DeliveryOut,
    EventAccepted,
    EventIn,
    EventOut,
    EventReplayed,
    EventReplayIn,
    EventSummary,
    ListOf,
    Page,
)

log = logging.getLogger("hookflow.api")
router = APIRouter(prefix="/v1/events", tags=["events"])

IDEMPOTENCY_HEADER = "Idempotency-Key"


@dataclass
class Ingested:
    event: Event
    delivery_count: int
    outbox_ids: list[str]
    replayed: bool = False  # True when an Idempotency-Key matched an earlier request


def _request_hash(body: EventIn) -> str:
    """Fingerprint of the request. Key order and whitespace don't matter; values do."""
    canonical = json.dumps({"event_type": body.event_type, "data": body.data}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _parse_idempotency_key(request: Request) -> str | None:
    key = request.headers.get(IDEMPOTENCY_HEADER)
    if key is None:
        return None
    if not 1 <= len(key) <= 255 or not all(0x21 <= ord(c) <= 0x7E for c in key):
        raise ApiError(
            422,
            f"{IDEMPOTENCY_HEADER} must be 1-255 printable ASCII characters with no spaces.",
            details=[{"loc": ["header", IDEMPOTENCY_HEADER], "msg": "Invalid idempotency key."}],
        )
    return key


def _existing(db: Session, user_id: str, key: str, request_hash: str, now: datetime) -> Ingested | None:
    row = db.scalar(
        select(IdempotencyKey).where(IdempotencyKey.user_id == user_id, IdempotencyKey.key == key).with_for_update()
    )
    if row is None:
        return None
    if row.expires_at <= now:
        db.execute(delete(IdempotencyKey).where(IdempotencyKey.user_id == user_id, IdempotencyKey.key == key))
        db.flush()
        return None
    if row.request_hash != request_hash:
        raise ApiError(
            409,
            f"This {IDEMPOTENCY_HEADER} was already used with a different request body. "
            "Use a new key for a new event.",
            code="idempotency_key_reused",
            details={"event_id": row.event_id},
        )
    event = db.get(Event, row.event_id)
    count = db.scalar(select(func.count()).where(Delivery.event_id == row.event_id)) or 0
    return Ingested(event=event, delivery_count=count, outbox_ids=[], replayed=True)


def _ingest_once(db: Session, user_id: str, body: EventIn, key: str | None) -> Ingested:
    now = datetime.now(UTC)
    request_hash = _request_hash(body)
    if key is not None:
        existing = _existing(db, user_id, key, request_hash, now)
        if existing is not None:
            db.commit()
            return existing

    endpoints = db.execute(
        select(Endpoint.id, Endpoint.max_attempts)
        .join(EndpointSubscription)
        .where(
            Endpoint.user_id == user_id,
            Endpoint.enabled.is_(True),
            Endpoint.archived_at.is_(None),
            EndpointSubscription.event_type.in_([body.event_type, "*"]),
        )
        .distinct()
    ).all()

    event = Event(
        id=new_id("evt"), user_id=user_id, event_type=body.event_type, payload=body.data,
        idempotency_key=key, created_at=now,
    )
    db.add(event)
    db.flush()
    deliveries = [
        Delivery(
            id=new_id("dlv"),
            user_id=user_id,
            event_id=event.id,
            endpoint_id=endpoint_id,
            status=DeliveryStatus.PENDING,
            attempt_count=0,
            max_attempts=max_attempts,
            next_attempt_at=now,
            created_at=now,
            updated_at=now,
        )
        for endpoint_id, max_attempts in endpoints
    ]
    db.add_all(deliveries)
    db.flush()
    outbox_ids = outbox.add(db, [d.id for d in deliveries], available_at=now)
    if key is not None:
        ttl = timedelta(hours=get_settings().idempotency_key_ttl_hours)
        db.add(IdempotencyKey(user_id=user_id, key=key, request_hash=request_hash, event_id=event.id,
                              created_at=now, expires_at=now + ttl))
    db.commit()
    return Ingested(event=event, delivery_count=len(deliveries), outbox_ids=outbox_ids)


def _ingest(db: Session, user_id: str, body: EventIn, key: str | None) -> Ingested:
    """Save the event, its deliveries and their queue messages in one transaction.

    Two concurrent requests with the same new Idempotency-Key both try to insert the key; Postgres makes the
    second wait for the first and then fail on the primary key. That one rolls back and retries, and the
    retry finds the first request's event.
    """
    try:
        return _ingest_once(db, user_id, body, key)
    except IntegrityError:
        db.rollback()
        if key is None:
            raise
        return _ingest_once(db, user_id, body, key)


@router.post(
    "",
    status_code=202,
    response_model=EventAccepted,
    openapi_extra={
        "requestBody": {"required": True, "content": {"application/json": {"schema": EventIn.model_json_schema()}}},
        "parameters": [
            {
                "name": IDEMPOTENCY_HEADER,
                "in": "header",
                "required": False,
                "schema": {"type": "string", "maxLength": 255},
                "description": "Retrying with the same key and body returns the original event instead of "
                "creating a new one (remembered for 24 hours).",
            }
        ],
    },
)
async def create_event(request: Request, response: Response, principal: CurrentPrincipal, db: DB) -> dict:
    max_bytes = get_settings().max_payload_bytes
    raw = await request.body()
    if len(raw) > max_bytes:
        raise ApiError(413, f"Request body exceeds the {max_bytes} byte limit.")
    key = _parse_idempotency_key(request)
    try:
        body = EventIn.model_validate(json.loads(raw))
    except json.JSONDecodeError:
        raise ApiError(422, "Request body must be valid JSON.") from None
    except ValidationError as exc:
        details = [{"loc": ["body", *e["loc"]], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        raise ApiError(422, "Request validation failed.", details=details) from None

    result = await run_in_threadpool(_ingest, db, principal.user.id, body, key)
    if result.replayed:
        response.headers["Idempotent-Replayed"] = "true"
    else:
        # Saved durably, queue messages included. Publishing now is just to start delivery immediately;
        # if Redis is down the outbox publisher sends them once it's back.
        await run_in_threadpool(outbox.publish_ids, result.outbox_ids)
        log.info("event accepted", extra={"event_id": result.event.id, "deliveries": result.delivery_count})
    return {
        "event_id": result.event.id,
        "created_at": result.event.created_at,
        "delivery_count": result.delivery_count,
    }


def _counts(db: Session, event_ids: list[str]) -> dict[str, DeliveryCounts]:
    out = {eid: DeliveryCounts() for eid in event_ids}
    if not event_ids:
        return out
    rows = db.execute(
        select(Delivery.event_id, Delivery.status, func.count())
        .where(Delivery.event_id.in_(event_ids))
        .group_by(Delivery.event_id, Delivery.status)
    ).all()
    for event_id, status, n in rows:
        c = out[event_id]
        setattr(c, status, n)
        c.total += n
    return out


def _owned_event(db: Session, principal: CurrentPrincipal, event_id: str) -> Event:
    event = db.scalar(select(Event).where(Event.id == event_id, Event.user_id == principal.user.id))
    if event is None:
        raise not_found("Event")
    return event


@router.get("", response_model=Page[EventSummary])
def list_events(
    principal: CurrentPrincipal,
    db: DB,
    limit: Limit = 25,
    cursor: Cursor = None,
    event_type: Annotated[str | None, Query(max_length=100)] = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
) -> dict:
    stmt = select(Event).where(Event.user_id == principal.user.id)
    if event_type:
        stmt = stmt.where(Event.event_type == event_type)
    if created_after:
        stmt = stmt.where(Event.created_at >= created_after)
    if created_before:
        stmt = stmt.where(Event.created_at < created_before)
    events, next_cursor = paginate(db, stmt, Event.id, limit, cursor)
    counts = _counts(db, [e.id for e in events])
    data = [
        EventSummary(id=e.id, event_type=e.event_type, created_at=e.created_at, deliveries=counts[e.id])
        for e in events
    ]
    return {"data": data, "next_cursor": next_cursor}


@router.get("/{event_id}", response_model=EventOut)
def get_event(event_id: str, principal: CurrentPrincipal, db: DB) -> EventOut:
    e = _owned_event(db, principal, event_id)
    return EventOut(
        id=e.id, event_type=e.event_type, created_at=e.created_at, data=e.payload,
        idempotency_key=e.idempotency_key, deliveries=_counts(db, [e.id])[e.id],
    )


@router.get("/{event_id}/deliveries", response_model=ListOf[DeliveryOut])
def list_event_deliveries(event_id: str, principal: CurrentPrincipal, db: DB) -> dict:
    _owned_event(db, principal, event_id)
    rows = db.scalars(
        select(Delivery)
        .where(Delivery.event_id == event_id, Delivery.user_id == principal.user.id)
        .order_by(Delivery.id)
    ).all()
    return {"data": [delivery_out(d) for d in rows]}


@router.post("/{event_id}/replay", status_code=202, response_model=EventReplayed)
def replay_event(
    event_id: str,
    principal: CurrentPrincipal,
    db: DB,
    body: Annotated[EventReplayIn | None, Body()] = None,
) -> dict:
    """Replay this event's failed and cancelled deliveries. Never creates a new event or new deliveries."""
    _owned_event(db, principal, event_id)
    stmt = select(Delivery).where(Delivery.event_id == event_id, Delivery.user_id == principal.user.id)
    if body and body.endpoint_ids:
        stmt = stmt.where(Delivery.endpoint_id.in_(body.endpoint_ids))
    deliveries = db.scalars(stmt.order_by(Delivery.id)).all()

    candidates, skipped = [], []
    for d in deliveries:
        reason = why_not_replayable(d)
        if reason:
            skipped.append({"delivery_id": d.id, "reason": reason})
        else:
            candidates.append(d)
    if not candidates:
        raise ApiError(409, "None of this event's deliveries can be replayed.", code="nothing_to_replay",
                       details=skipped)

    enforce_rate_limit(principal.user.id, len(candidates))
    replayed = []
    for d in candidates:
        r = replay(db, principal, d)
        if r is None:
            skipped.append({"delivery_id": d.id, "reason": "Changed while being replayed."})
        else:
            replayed.append((d, r))
    message_ids = outbox.add(db, [d.id for d, _ in replayed])
    audit.record(db, principal, "event.replayed", "event", event_id, {"deliveries": [d.id for d, _ in replayed]})
    db.commit()
    outbox.publish_ids(message_ids)
    for d, _ in replayed:
        db.refresh(d)
    return {
        "replayed": [{"replay": replay_out(r), "delivery": delivery_out(d)} for d, r in replayed],
        "skipped": skipped,
    }
