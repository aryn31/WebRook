from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from app import audit, outbox, ratelimit
from app.config import get_settings
from app.deps import DB, CurrentPrincipal, DeliveriesRead, DeliveriesReplay
from app.errors import ApiError, not_found
from app.models import Delivery, DeliveryAttempt, DeliveryReplay, DeliveryStatus, Endpoint, Event
from app.pagination import Cursor, Limit, paginate
from app.replay import enforce_rate_limit, replay, replay_out, why_not_replayable
from app.schemas import (
    AttemptOut, BulkReplayIn, BulkReplayOut, DeliveryOut, DeliveryReplayed, ListOf, Page, ReplayOut,
)

router = APIRouter(prefix="/v1/deliveries", tags=["deliveries"])


def delivery_out(d: Delivery) -> DeliveryOut:
    return DeliveryOut(
        id=d.id,
        event_id=d.event_id,
        event_type=d.event.event_type,
        endpoint_id=d.endpoint_id,
        endpoint_url=d.endpoint.url,
        status=d.status,
        attempt_count=d.attempt_count,
        max_attempts=d.max_attempts,
        run_attempt_count=d.attempt_count - d.retry_base_attempt,
        run_max_attempts=d.max_attempts - d.retry_base_attempt,
        next_attempt_at=d.next_attempt_at,
        last_status_code=d.last_status_code,
        last_error=d.last_error,
        delivered_at=d.delivered_at,
        replay_count=d.replay_count,
        last_replayed_at=d.last_replayed_at,
        replayable=why_not_replayable(d) is None,
        created_at=d.created_at,
        updated_at=d.updated_at,
    )


def _owned(db: DB, principal: CurrentPrincipal, delivery_id: str) -> Delivery:
    d = db.scalar(select(Delivery).where(Delivery.id == delivery_id, Delivery.user_id == principal.user.id))
    if d is None:
        raise not_found("Delivery")
    return d


@router.get("", response_model=Page[DeliveryOut])
def list_deliveries(
    principal: DeliveriesRead,
    db: DB,
    limit: Limit = 25,
    cursor: Cursor = None,
    status: DeliveryStatus | None = None,
    endpoint_id: Annotated[str | None, Query(max_length=32)] = None,
    event_id: Annotated[str | None, Query(max_length=32)] = None,
) -> dict:
    stmt = select(Delivery).where(Delivery.user_id == principal.user.id)
    if status:
        stmt = stmt.where(Delivery.status == status)
    if endpoint_id:
        stmt = stmt.where(Delivery.endpoint_id == endpoint_id)
    if event_id:
        stmt = stmt.where(Delivery.event_id == event_id)
    rows, next_cursor = paginate(db, stmt, Delivery.id, limit, cursor)
    return {"data": [delivery_out(d) for d in rows], "next_cursor": next_cursor}


@router.post("/replay", response_model=BulkReplayOut)
def bulk_replay(body: BulkReplayIn, principal: DeliveriesReplay, db: DB) -> dict:
    """Replay many failed or cancelled deliveries at once, oldest first, up to ``limit`` per request.

    Only deliveries to enabled endpoints are matched (the others can't be replayed). Replayed deliveries leave
    the failed state, so calling again with the same filters continues with the next batch.
    """
    ratelimit.enforce(f"bulk_replay:{principal.user.id}", get_settings().bulk_replay_rate_limit_per_minute)
    stmt = (
        select(Delivery)
        .join(Endpoint, Endpoint.id == Delivery.endpoint_id)
        .where(
            Delivery.user_id == principal.user.id,
            Delivery.status.in_(body.statuses),
            Endpoint.enabled.is_(True),
            Endpoint.archived_at.is_(None),
        )
    )
    if body.endpoint_id:
        stmt = stmt.where(Delivery.endpoint_id == body.endpoint_id)
    if body.event_type:
        stmt = stmt.join(Event, Event.id == Delivery.event_id).where(Event.event_type == body.event_type)
    if body.created_after:
        stmt = stmt.where(Delivery.created_at >= body.created_after)
    if body.created_before:
        stmt = stmt.where(Delivery.created_at < body.created_before)
    rows = db.scalars(stmt.order_by(Delivery.id).limit(body.limit + 1)).unique().all()
    has_more = len(rows) > body.limit
    rows = rows[: body.limit]

    candidates, skipped = [], []
    for d in rows:
        reason = why_not_replayable(d)
        if reason:
            skipped.append({"delivery_id": d.id, "reason": reason})
        else:
            candidates.append(d)
    if body.dry_run:
        return {"matched": len(rows), "replayed": [d.id for d in candidates], "skipped": skipped,
                "has_more": has_more, "dry_run": True}

    replayed: list[str] = []
    for d in candidates:
        if replay(db, principal, d) is None:
            skipped.append({"delivery_id": d.id, "reason": "Changed while being replayed."})
        else:
            replayed.append(d.id)
    message_ids = outbox.add(db, replayed)
    if replayed:
        filters = body.model_dump(mode="json", exclude={"dry_run"}, exclude_none=True)
        audit.record(db, principal, "deliveries.bulk_replayed", None, None,
                     {"filters": filters, "count": len(replayed)})
    db.commit()
    outbox.publish_ids(message_ids)
    return {"matched": len(rows), "replayed": replayed, "skipped": skipped, "has_more": has_more,
            "dry_run": False}


@router.get("/{delivery_id}", response_model=DeliveryOut)
def get_delivery(delivery_id: str, principal: DeliveriesRead, db: DB) -> DeliveryOut:
    return delivery_out(_owned(db, principal, delivery_id))


@router.get("/{delivery_id}/attempts", response_model=ListOf[AttemptOut])
def list_attempts(delivery_id: str, principal: DeliveriesRead, db: DB) -> dict:
    _owned(db, principal, delivery_id)
    rows = db.scalars(
        select(DeliveryAttempt)
        .where(DeliveryAttempt.delivery_id == delivery_id)
        .order_by(DeliveryAttempt.attempt_number, DeliveryAttempt.started_at)
    ).all()
    return {"data": rows}


@router.post("/{delivery_id}/replay", status_code=202, response_model=DeliveryReplayed)
def replay_delivery(delivery_id: str, principal: DeliveriesReplay, db: DB) -> dict:
    d = _owned(db, principal, delivery_id)
    reason = why_not_replayable(d)
    if reason:
        raise ApiError(409, reason, code="not_replayable")
    enforce_rate_limit(principal.user.id, 1)
    r = replay(db, principal, d)
    if r is None:
        raise ApiError(409, "This delivery changed while it was being replayed. Refresh and try again.",
                       code="not_replayable")
    message_ids = outbox.add(db, [d.id])
    db.commit()
    outbox.publish_ids(message_ids)
    db.refresh(d)
    return {"replay": replay_out(r), "delivery": delivery_out(d)}


@router.get("/{delivery_id}/replays", response_model=ListOf[ReplayOut])
def list_replays(delivery_id: str, principal: DeliveriesRead, db: DB) -> dict:
    _owned(db, principal, delivery_id)
    rows = db.scalars(
        select(DeliveryReplay).where(DeliveryReplay.delivery_id == delivery_id).order_by(DeliveryReplay.id)
    ).all()
    return {"data": [replay_out(r) for r in rows]}
