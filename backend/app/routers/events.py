import json
import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.deps import DB, CurrentPrincipal
from app.errors import ApiError, not_found
from app.ids import new_id
from app.models import Delivery, DeliveryStatus, Endpoint, EndpointSubscription, Event
from app.pagination import Cursor, Limit, paginate
from app.queue import enqueue_delivery
from app.routers.deliveries import delivery_out
from app.schemas import DeliveryCounts, DeliveryOut, EventAccepted, EventIn, EventOut, EventSummary, ListOf, Page

log = logging.getLogger("hookflow.api")
router = APIRouter(prefix="/v1/events", tags=["events"])


def _ingest(db: Session, user_id: str, body: EventIn) -> tuple[Event, list[str]]:
    """Save the event and one delivery per subscribed endpoint in a single transaction."""
    endpoint_ids = db.scalars(
        select(Endpoint.id)
        .join(EndpointSubscription)
        .where(
            Endpoint.user_id == user_id,
            Endpoint.enabled.is_(True),
            Endpoint.archived_at.is_(None),
            EndpointSubscription.event_type.in_([body.event_type, "*"]),
        )
        .distinct()
    ).all()

    now = datetime.now(UTC)
    event = Event(id=new_id("evt"), user_id=user_id, event_type=body.event_type, payload=body.data, created_at=now)
    db.add(event)
    db.flush()
    max_attempts = get_settings().delivery_max_attempts
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
            enqueued_at=now,
            created_at=now,
            updated_at=now,
        )
        for endpoint_id in endpoint_ids
    ]
    db.add_all(deliveries)
    db.commit()
    return event, [d.id for d in deliveries]


@router.post(
    "",
    status_code=202,
    response_model=EventAccepted,
    openapi_extra={
        "requestBody": {"required": True, "content": {"application/json": {"schema": EventIn.model_json_schema()}}}
    },
)
async def create_event(request: Request, principal: CurrentPrincipal, db: DB) -> dict:
    max_bytes = get_settings().max_payload_bytes
    raw = await request.body()
    if len(raw) > max_bytes:
        raise ApiError(413, f"Request body exceeds the {max_bytes} byte limit.")
    try:
        body = EventIn.model_validate(json.loads(raw))
    except json.JSONDecodeError:
        raise ApiError(422, "Request body must be valid JSON.") from None
    except ValidationError as exc:
        details = [{"loc": ["body", *e["loc"]], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        raise ApiError(422, "Request validation failed.", details=details) from None

    event, delivery_ids = await run_in_threadpool(_ingest, db, principal.user.id, body)
    # The event is durably saved at this point. Queueing is best effort: if Redis is down,
    # the sweeper finds these deliveries in Postgres and queues them a little later.
    for delivery_id in delivery_ids:
        if not await run_in_threadpool(enqueue_delivery, delivery_id):
            break
    log.info("event accepted", extra={"event_id": event.id, "deliveries": len(delivery_ids)})
    return {"event_id": event.id, "created_at": event.created_at, "delivery_count": len(delivery_ids)}


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
        id=e.id, event_type=e.event_type, created_at=e.created_at, data=e.payload, deliveries=_counts(db, [e.id])[e.id]
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
