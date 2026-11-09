"""Consumers: an account's own customers, who manage their own endpoints in the customer portal."""

from datetime import timedelta

from fastapi import APIRouter, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import audit, portal
from app.config import get_settings
from app.deps import DB, EndpointsRead, EndpointsWrite
from app.errors import ApiError, not_found
from app.models import Consumer, Endpoint
from app.pagination import Cursor, Limit, paginate
from app.routers.endpoints import archive
from app.schemas import ConsumerIn, ConsumerOut, ConsumerPatch, Page, PortalLinkIn, PortalLinkOut

router = APIRouter(prefix="/v1/consumers", tags=["consumers"])


def get_consumer(db, account_id: str, ref: str) -> Consumer:
    """A consumer by uid or ID, in this account only."""
    c = db.scalar(select(Consumer).where(Consumer.user_id == account_id, (Consumer.uid == ref) | (Consumer.id == ref)))
    if c is None:
        raise not_found("Consumer")
    return c


def _counts(db, ids: list[str]) -> dict[str, int]:
    if not ids:
        return {}
    rows = db.execute(
        select(Endpoint.consumer_id, func.count())
        .where(Endpoint.consumer_id.in_(ids), Endpoint.archived_at.is_(None))
        .group_by(Endpoint.consumer_id)
    ).all()
    return dict(rows)


def _out(c: Consumer, count: int) -> ConsumerOut:
    return ConsumerOut(id=c.id, uid=c.uid, name=c.name, endpoint_count=count, created_at=c.created_at)


@router.post("", status_code=201, response_model=ConsumerOut)
def create_consumer(body: ConsumerIn, principal: EndpointsWrite, db: DB) -> ConsumerOut:
    c = Consumer(user_id=principal.user.id, uid=body.uid, name=body.name)
    db.add(c)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, f"A consumer with uid '{body.uid}' already exists.", code="consumer_exists") from None
    audit.record(db, principal, "consumer.created", "consumer", c.id, {"uid": c.uid, "name": c.name})
    db.commit()
    db.refresh(c)
    return _out(c, 0)


@router.get("", response_model=Page[ConsumerOut])
def list_consumers(principal: EndpointsRead, db: DB, limit: Limit = 25, cursor: Cursor = None) -> dict:
    stmt = select(Consumer).where(Consumer.user_id == principal.user.id)
    data, next_cursor = paginate(db, stmt, Consumer.id, limit, cursor)
    counts = _counts(db, [c.id for c in data])
    return {"data": [_out(c, counts.get(c.id, 0)) for c in data], "next_cursor": next_cursor}


@router.get("/{ref}", response_model=ConsumerOut)
def get_consumer_route(ref: str, principal: EndpointsRead, db: DB) -> ConsumerOut:
    c = get_consumer(db, principal.user.id, ref)
    return _out(c, _counts(db, [c.id]).get(c.id, 0))


@router.patch("/{ref}", response_model=ConsumerOut)
def update_consumer(ref: str, body: ConsumerPatch, principal: EndpointsWrite, db: DB) -> ConsumerOut:
    c = get_consumer(db, principal.user.id, ref)
    if "name" in body.model_fields_set and body.name != c.name:
        audit.record(db, principal, "consumer.updated", "consumer", c.id, {"name": {"from": c.name, "to": body.name}})
        c.name = body.name
    db.commit()
    db.refresh(c)
    return _out(c, _counts(db, [c.id]).get(c.id, 0))


@router.delete("/{ref}", status_code=204)
def delete_consumer(ref: str, principal: EndpointsWrite, db: DB) -> Response:
    """Delete a consumer. Their endpoints are deleted too, and anything not yet sent to them is cancelled."""
    c = get_consumer(db, principal.user.id, ref)
    endpoints = db.scalars(select(Endpoint).where(Endpoint.consumer_id == c.id, Endpoint.archived_at.is_(None))).all()
    for e in endpoints:
        archive(db, principal, e)
    audit.record(db, principal, "consumer.deleted", "consumer", c.id, {"uid": c.uid, "endpoints": len(endpoints)})
    db.delete(c)  # endpoints and events keep their history; their consumer_id becomes NULL
    db.commit()
    return Response(status_code=204)


@router.post("/{ref}/portal", response_model=PortalLinkOut)
def create_portal_link(ref: str, principal: EndpointsWrite, db: DB, body: PortalLinkIn | None = None) -> dict:
    """A link to this consumer's portal, for embedding in your app. Anyone with it can manage the consumer's
    endpoints until it expires, so create it when the consumer opens the page, and don't store it."""
    body = body or PortalLinkIn()
    c = get_consumer(db, principal.user.id, ref)
    ttl = timedelta(minutes=body.ttl_minutes or get_settings().portal_link_ttl_minutes)
    token, expires = portal.create_token(principal.user.id, c.id, ttl, body.brand_name)
    audit.record(db, principal, "consumer.portal_opened", "consumer", c.id,
                 {"uid": c.uid, "expires_in_minutes": int(ttl.total_seconds() // 60)})
    db.commit()
    return {"url": portal.portal_url(token), "token": token, "expires_at": expires}

