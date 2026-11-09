"""The customer portal API: one consumer managing their own endpoints with a portal token.

Every route is scoped twice: to the token's account and to its consumer. A consumer can never see the account's
own endpoints, another consumer's, or any other data. Actions are recorded in the account's audit log with
actor type "portal".
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select

from app import audit, outbox, portal, ratelimit
from app.clientip import client_ip
from app.deps import DB, Principal
from app.errors import ApiError, not_found
from app.models import Consumer, Delivery, DeliveryAttempt, Endpoint, EndpointSubscription, Event, User
from app.pagination import Cursor, Limit, paginate
from app.replay import enforce_rate_limit, replay, replay_out, why_not_replayable
from app.routers import endpoints as ep
from app.routers.deliveries import delivery_out
from app.schemas import (
    AttemptOut, DeliveryOut, DeliveryReplayed, EndpointCreated, EndpointOut, EndpointWithHealth, ListOf, Page,
    PortalConsumer, PortalEndpointIn, PortalEndpointPatch, PortalMeOut, SigningSecret,
)

router = APIRouter(prefix="/v1/portal", tags=["customer portal"])

REQUESTS_PER_MINUTE = 120
EVENT_TYPE_WINDOW = timedelta(days=30)


@dataclass
class PortalContext:
    account: User
    consumer: Consumer
    claims: portal.PortalClaims
    principal: Principal


def _unauthorized(message: str, code: str) -> ApiError:
    return ApiError(401, message, code=code)


def get_portal(request: Request, db: DB) -> PortalContext:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token.startswith(portal.PREFIX):
        raise _unauthorized("Open the portal from a link created by the app.", "portal_link_invalid")
    claims = portal.read_token(token)
    if claims is None:
        raise _unauthorized("This portal link has expired or isn't valid. Open the portal again from the app.",
                            "portal_link_expired")
    consumer = db.scalar(select(Consumer).where(Consumer.id == claims.consumer_id,
                                                Consumer.user_id == claims.account_id))
    account = db.get(User, claims.account_id)
    if consumer is None or account is None:
        raise _unauthorized("This portal no longer exists.", "portal_link_invalid")
    ratelimit.enforce(f"portal:{consumer.id}", REQUESTS_PER_MINUTE)
    principal = Principal(user=account, via="portal", ip=client_ip(request))
    return PortalContext(account, consumer, claims, principal)


Portal = Annotated[PortalContext, Depends(get_portal)]


def _endpoint(db, p: PortalContext, endpoint_id: str) -> Endpoint:
    e = db.scalar(select(Endpoint).where(
        Endpoint.id == endpoint_id, Endpoint.user_id == p.account.id, Endpoint.consumer_id == p.consumer.id,
        Endpoint.archived_at.is_(None),
    ))
    if e is None:
        raise not_found("Endpoint")
    return e


def _delivery(db, p: PortalContext, delivery_id: str) -> Delivery:
    d = db.scalar(
        select(Delivery).join(Endpoint, Endpoint.id == Delivery.endpoint_id)
        .where(Delivery.id == delivery_id, Delivery.user_id == p.account.id, Endpoint.consumer_id == p.consumer.id)
    )
    if d is None:
        raise not_found("Delivery")
    return d


@router.get("/me", response_model=PortalMeOut)
def me(p: Portal, db: DB) -> dict:
    since = datetime.now(UTC) - EVENT_TYPE_WINDOW
    base = select(Event.event_type).where(Event.user_id == p.account.id, Event.created_at >= since).distinct().limit(100)
    types = db.scalars(base.where(Event.consumer_id == p.consumer.id)).all() or db.scalars(base).all()
    return {
        "consumer": PortalConsumer(id=p.consumer.id, uid=p.consumer.uid, name=p.consumer.name),
        "brand_name": p.claims.brand_name,
        "expires_at": p.claims.expires_at,
        "event_types": sorted(types),
    }


@router.get("/endpoints", response_model=ListOf[EndpointWithHealth])
def list_endpoints(p: Portal, db: DB) -> dict:
    rows = db.scalars(select(Endpoint).where(
        Endpoint.user_id == p.account.id, Endpoint.consumer_id == p.consumer.id, Endpoint.archived_at.is_(None),
    ).order_by(Endpoint.id)).all()
    return {"data": ep.with_health(db, list(rows))}


@router.post("/endpoints", status_code=201, response_model=EndpointCreated)
def create_endpoint(body: PortalEndpointIn, p: Portal, db: DB) -> dict:
    return ep.create(db, p.principal, url=body.url, description=body.description, event_types=body.event_types,
                     consumer=p.consumer)


@router.get("/endpoints/{endpoint_id}", response_model=EndpointWithHealth)
def get_endpoint(endpoint_id: str, p: Portal, db: DB) -> dict:
    return ep.with_health(db, [_endpoint(db, p, endpoint_id)])[0]


@router.patch("/endpoints/{endpoint_id}", response_model=EndpointOut)
def update_endpoint(endpoint_id: str, body: PortalEndpointPatch, p: Portal, db: DB) -> Endpoint:
    e = _endpoint(db, p, endpoint_id)
    fields = body.model_fields_set
    changes: dict = {}
    if "url" in fields and body.url is not None:
        url = ep._check_url(body.url)
        if url != e.url:
            changes["url"] = {"from": e.url, "to": url}
            e.url = url
            e.security_check = None
    if "description" in fields and body.description != e.description:
        changes["description"] = {"from": e.description, "to": body.description}
        e.description = body.description
    if "event_types" in fields and body.event_types is not None and body.event_types != e.event_types:
        changes["event_types"] = {"from": e.event_types, "to": body.event_types}
        e.subscriptions = [EndpointSubscription(event_type=t) for t in body.event_types]
    if "enabled" in fields and body.enabled is not None and body.enabled != e.enabled:
        if not body.enabled:
            ep._cancel_unsent(db, e.id, "Cancelled because the endpoint was disabled.")
        changes["enabled"] = {"from": e.enabled, "to": body.enabled}
        e.enabled = body.enabled
    if changes:
        e.updated_at = datetime.now(UTC)
        audit.record(db, p.principal, "endpoint.updated", "endpoint", e.id,
                     {"changes": changes, "consumer": p.consumer.uid})
    db.commit()
    db.refresh(e)
    return e


@router.delete("/endpoints/{endpoint_id}", status_code=204)
def delete_endpoint(endpoint_id: str, p: Portal, db: DB) -> Response:
    ep.archive(db, p.principal, _endpoint(db, p, endpoint_id))
    db.commit()
    return Response(status_code=204)


@router.get("/endpoints/{endpoint_id}/secret", response_model=SigningSecret)
def get_secret(endpoint_id: str, p: Portal, db: DB) -> dict:
    e = _endpoint(db, p, endpoint_id)
    audit.record(db, p.principal, "endpoint.secret_viewed", "endpoint", e.id, {"consumer": p.consumer.uid})
    db.commit()
    return ep._secret_out(e)


@router.post("/endpoints/{endpoint_id}/security-check", response_model=EndpointOut)
def security_check(endpoint_id: str, p: Portal, db: DB) -> Endpoint:
    return ep.check_security(db, p.principal, _endpoint(db, p, endpoint_id), lambda: _endpoint(db, p, endpoint_id))


@router.get("/endpoints/{endpoint_id}/deliveries", response_model=Page[DeliveryOut])
def list_deliveries(endpoint_id: str, p: Portal, db: DB, limit: Limit = 25, cursor: Cursor = None) -> dict:
    e = _endpoint(db, p, endpoint_id)
    stmt = select(Delivery).where(Delivery.user_id == p.account.id, Delivery.endpoint_id == e.id)
    data, next_cursor = paginate(db, stmt, Delivery.id, limit, cursor)
    return {"data": [delivery_out(d) for d in data], "next_cursor": next_cursor}


@router.get("/deliveries/{delivery_id}/attempts", response_model=ListOf[AttemptOut])
def list_attempts(delivery_id: str, p: Portal, db: DB) -> dict:
    _delivery(db, p, delivery_id)
    rows = db.scalars(select(DeliveryAttempt).where(DeliveryAttempt.delivery_id == delivery_id)
                      .order_by(DeliveryAttempt.attempt_number, DeliveryAttempt.started_at)).all()
    return {"data": rows}


@router.post("/deliveries/{delivery_id}/replay", status_code=202, response_model=DeliveryReplayed)
def replay_delivery(delivery_id: str, p: Portal, db: DB) -> dict:
    d = _delivery(db, p, delivery_id)
    reason = why_not_replayable(d)
    if reason:
        raise ApiError(409, reason, code="not_replayable")
    enforce_rate_limit(p.account.id, 1)
    r = replay(db, p.principal, d)
    if r is None:
        raise ApiError(409, "This delivery changed while it was being replayed. Refresh and try again.",
                       code="not_replayable")
    message_ids = outbox.add(db, [d.id])
    db.commit()
    outbox.publish_ids(message_ids)
    db.refresh(d)
    return {"replay": replay_out(r), "delivery": delivery_out(d)}
