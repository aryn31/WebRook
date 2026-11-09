from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Body, Query, Response
from sqlalchemy import case, func, literal, select, update

from app import audit, ratelimit, security_check
from app.config import get_settings
from app.deps import DB, CurrentPrincipal, EndpointsRead, EndpointsWrite
from app.errors import ApiError, not_found
from app.models import Consumer, Delivery, DeliveryAttempt, DeliveryStatus, Endpoint, EndpointSubscription
from app.pagination import Cursor, Limit, paginate
from app.schemas import (
    EndpointCreated,
    EndpointIn,
    EndpointOut,
    EndpointPatch,
    EndpointWithHealth,
    Page,
    RotateSecretIn,
    SigningSecret,
)
from app.security import decrypt_secret, encrypt_secret, new_signing_secret
from app.urlguard import validate_url_format

router = APIRouter(prefix="/v1/endpoints", tags=["endpoints"])


def _get_owned(db: DB, principal: CurrentPrincipal, endpoint_id: str) -> Endpoint:
    endpoint = db.scalar(
        select(Endpoint).where(
            Endpoint.id == endpoint_id,
            Endpoint.user_id == principal.user.id,
            Endpoint.archived_at.is_(None),
        )
    )
    if endpoint is None:
        raise not_found("Endpoint")
    return endpoint


def _check_url(url: str) -> str:
    try:
        return validate_url_format(url)
    except ValueError as exc:
        raise ApiError(422, str(exc), details=[{"loc": ["body", "url"], "msg": str(exc)}]) from None


def _cancel_unsent(db: DB, endpoint_id: str, reason: str) -> None:
    db.execute(
        update(Delivery)
        .where(
            Delivery.endpoint_id == endpoint_id,
            Delivery.status.in_([DeliveryStatus.PENDING, DeliveryStatus.RETRYING]),
        )
        .values(status=DeliveryStatus.CANCELLED, next_attempt_at=None, last_error=reason)
    )


HEALTH_WINDOW = timedelta(hours=24)


def _health(db: DB, endpoint_ids: list[str]) -> dict[str, dict]:
    """Attempt counts and the latest attempt per endpoint over the last 24 hours."""
    out = {
        eid: {"state": "idle", "attempts": 0, "successes": 0, "success_rate": None, "last_attempt_at": None,
              "last_success": None, "last_status_code": None, "last_error": None}
        for eid in endpoint_ids
    }
    if not endpoint_ids:
        return out
    since = datetime.now(UTC) - HEALTH_WINDOW
    recent = (DeliveryAttempt.completed_at >= since, Delivery.endpoint_id.in_(endpoint_ids))
    for eid, attempts, successes in db.execute(
        select(Delivery.endpoint_id, func.count(),
               func.sum(case((DeliveryAttempt.success.is_(True), 1), else_=literal(0))))
        .join(Delivery, Delivery.id == DeliveryAttempt.delivery_id)
        .where(*recent)
        .group_by(Delivery.endpoint_id)
    ):
        out[eid] |= {"attempts": attempts, "successes": int(successes or 0)}
    for eid, at, ok, code, error in db.execute(
        select(Delivery.endpoint_id, DeliveryAttempt.completed_at, DeliveryAttempt.success,
               DeliveryAttempt.response_status, DeliveryAttempt.error)
        .join(Delivery, Delivery.id == DeliveryAttempt.delivery_id)
        .where(*recent)
        .order_by(Delivery.endpoint_id, DeliveryAttempt.completed_at.desc())
        .distinct(Delivery.endpoint_id)
    ):
        out[eid] |= {"last_attempt_at": at, "last_success": ok, "last_status_code": code, "last_error": error}
    for h in out.values():
        if h["attempts"]:
            rate = h["successes"] / h["attempts"]
            h["success_rate"] = rate
            if rate >= 0.95:
                h["state"] = "healthy"
            elif not h["last_success"] and rate < 0.5:
                h["state"] = "failing"
            else:
                h["state"] = "degraded"
    return out


def with_health(db, endpoints: list[Endpoint]) -> list[dict]:
    health = _health(db, [e.id for e in endpoints])
    return [{**EndpointOut.model_validate(e).model_dump(), "health": health[e.id]} for e in endpoints]


@router.get("", response_model=Page[EndpointWithHealth])
def list_endpoints(
    principal: EndpointsRead, db: DB, limit: Limit = 25, cursor: Cursor = None,
    consumer: Annotated[str | None, Query(description="A consumer's uid or ID: list their endpoints instead of "
                                                       "the account's own.")] = None,
) -> dict:
    stmt = select(Endpoint).where(Endpoint.user_id == principal.user.id, Endpoint.archived_at.is_(None))
    if consumer is None:
        stmt = stmt.where(Endpoint.consumer_id.is_(None))
    else:
        c = db.scalar(select(Consumer).where(Consumer.user_id == principal.user.id,
                                             (Consumer.id == consumer) | (Consumer.uid == consumer)))
        if c is None:
            raise not_found("Consumer")
        stmt = stmt.where(Endpoint.consumer_id == c.id)
    data, next_cursor = paginate(db, stmt, Endpoint.id, limit, cursor)
    return {"data": with_health(db, data), "next_cursor": next_cursor}


def create(db, principal, *, url: str, description: str | None, event_types: list[str], enabled: bool = True,
           max_attempts: int | None = None, retry_schedule: list[int] | None = None,
           consumer: Consumer | None = None) -> dict:
    """Add an endpoint for the account, or for one of its consumers. Returns it with its signing secret."""
    url = _check_url(url)
    s = get_settings()
    scope = Endpoint.consumer_id == consumer.id if consumer else Endpoint.consumer_id.is_(None)
    count = db.scalar(
        select(func.count()).where(Endpoint.user_id == principal.user.id, Endpoint.archived_at.is_(None), scope)
    )
    limit = s.max_endpoints_per_consumer if consumer else s.max_endpoints_per_account
    if (count or 0) >= limit:
        who = "Each consumer" if consumer else "Accounts"
        raise ApiError(409, f"{who} can have at most {limit} endpoints.", code="endpoint_limit_reached")

    secret = new_signing_secret()
    endpoint = Endpoint(
        user_id=principal.user.id,
        consumer_id=consumer.id if consumer else None,
        url=url,
        description=description,
        enabled=enabled,
        max_attempts=max_attempts or s.delivery_max_attempts,
        retry_schedule=retry_schedule,
        secret_encrypted=encrypt_secret(secret),
        subscriptions=[EndpointSubscription(event_type=t) for t in event_types],
    )
    db.add(endpoint)
    db.flush()
    details = {"url": url, "event_types": event_types, "max_attempts": endpoint.max_attempts,
               "retry_schedule": retry_schedule}
    if consumer:
        details["consumer"] = consumer.uid
    audit.record(db, principal, "endpoint.created", "endpoint", endpoint.id, details)
    db.commit()
    db.refresh(endpoint)
    return {**EndpointOut.model_validate(endpoint).model_dump(), "signing_secret": secret}


@router.post("", status_code=201, response_model=EndpointCreated)
def create_endpoint(body: EndpointIn, principal: EndpointsWrite, db: DB) -> dict:
    return create(db, principal, url=body.url, description=body.description, event_types=body.event_types,
                  enabled=body.enabled, max_attempts=body.max_attempts, retry_schedule=body.retry_schedule)


@router.get("/{endpoint_id}", response_model=EndpointWithHealth)
def get_endpoint(endpoint_id: str, principal: EndpointsRead, db: DB) -> dict:
    endpoint = _get_owned(db, principal, endpoint_id)
    return {**EndpointOut.model_validate(endpoint).model_dump(), "health": _health(db, [endpoint.id])[endpoint.id]}


@router.patch("/{endpoint_id}", response_model=EndpointOut)
def update_endpoint(endpoint_id: str, body: EndpointPatch, principal: EndpointsWrite, db: DB) -> Endpoint:
    endpoint = _get_owned(db, principal, endpoint_id)
    fields = body.model_fields_set
    changes: dict = {}
    if "url" in fields and body.url is not None:
        url = _check_url(body.url)
        if url != endpoint.url:
            changes["url"] = {"from": endpoint.url, "to": url}
            endpoint.security_check = None  # it checked the old URL
        endpoint.url = url
    if "description" in fields and body.description != endpoint.description:
        changes["description"] = {"from": endpoint.description, "to": body.description}
        endpoint.description = body.description
    if "event_types" in fields and body.event_types is not None and body.event_types != endpoint.event_types:
        changes["event_types"] = {"from": endpoint.event_types, "to": body.event_types}
        endpoint.subscriptions = [EndpointSubscription(event_type=t) for t in body.event_types]
    if "max_attempts" in fields and body.max_attempts is not None and body.max_attempts != endpoint.max_attempts:
        # Applies to deliveries created from now on; existing ones keep the limit they started with.
        changes["max_attempts"] = {"from": endpoint.max_attempts, "to": body.max_attempts}
        endpoint.max_attempts = body.max_attempts
    if "retry_schedule" in fields and body.retry_schedule != endpoint.retry_schedule:
        # Takes effect from the next retry, including deliveries already retrying.
        changes["retry_schedule"] = {"from": endpoint.retry_schedule, "to": body.retry_schedule}
        endpoint.retry_schedule = body.retry_schedule
    if "enabled" in fields and body.enabled is not None and body.enabled != endpoint.enabled:
        if not body.enabled:
            _cancel_unsent(db, endpoint.id, "Cancelled because the endpoint was disabled.")
        changes["enabled"] = {"from": endpoint.enabled, "to": body.enabled}
        endpoint.enabled = body.enabled
    if changes:
        endpoint.updated_at = datetime.now(UTC)
        audit.record(db, principal, "endpoint.updated", "endpoint", endpoint.id, {"changes": changes})
    db.commit()
    db.refresh(endpoint)
    return endpoint


@router.delete("/{endpoint_id}", status_code=204)
def archive_endpoint(endpoint_id: str, principal: EndpointsWrite, db: DB) -> Response:
    archive(db, principal, _get_owned(db, principal, endpoint_id))
    db.commit()
    return Response(status_code=204)


def archive(db, principal, endpoint: Endpoint) -> None:
    """Delete (archive) an endpoint and cancel what it hadn't been sent yet. The caller commits."""
    endpoint.archived_at = datetime.now(UTC)
    endpoint.enabled = False
    _cancel_unsent(db, endpoint.id, "Cancelled because the endpoint was deleted.")
    audit.record(db, principal, "endpoint.archived", "endpoint", endpoint.id, {"url": endpoint.url})


SECURITY_CHECKS_PER_MINUTE = 6


@router.post("/{endpoint_id}/security-check", response_model=EndpointOut)
def run_security_check(endpoint_id: str, principal: EndpointsWrite, db: DB) -> Endpoint:
    """Check whether the endpoint verifies signatures: send it one genuine and four forged test requests."""
    endpoint = _get_owned(db, principal, endpoint_id)
    return check_security(db, principal, endpoint, lambda: _get_owned(db, principal, endpoint_id))


def check_security(db, principal, endpoint: Endpoint, reload) -> Endpoint:
    """Run the receiver security check and save the result. ``reload`` fetches the endpoint again afterwards."""
    endpoint_id = endpoint.id
    ratelimit.enforce(f"security-check:{endpoint.id}", SECURITY_CHECKS_PER_MINUTE)
    signing = [decrypt_secret(endpoint.secret_encrypted)]
    if endpoint.previous_secret_encrypted and endpoint.previous_secret_expires_at and (
        endpoint.previous_secret_expires_at > datetime.now(UTC)
    ):
        signing.append(decrypt_secret(endpoint.previous_secret_encrypted))
    url = endpoint.url
    db.commit()  # don't hold a transaction open while waiting on the endpoint
    result = security_check.run(endpoint_id, url, signing)
    endpoint = reload()
    if endpoint.url == url:  # unless the URL changed meanwhile
        endpoint.security_check = result
    audit.record(db, principal, "endpoint.security_checked", "endpoint", endpoint.id, {"verdict": result["verdict"]})
    db.commit()
    db.refresh(endpoint)
    return endpoint


def _secret_out(endpoint: Endpoint) -> dict:
    expires = endpoint.previous_secret_expires_at
    return {
        "signing_secret": decrypt_secret(endpoint.secret_encrypted),
        "previous_secret_expires_at": expires if expires and expires > datetime.now(UTC) else None,
    }


@router.get("/{endpoint_id}/secret", response_model=SigningSecret)
def get_secret(endpoint_id: str, principal: EndpointsWrite, db: DB) -> dict:
    endpoint = _get_owned(db, principal, endpoint_id)
    audit.record(db, principal, "endpoint.secret_viewed", "endpoint", endpoint.id)
    db.commit()
    return _secret_out(endpoint)


@router.post("/{endpoint_id}/rotate-secret", response_model=SigningSecret)
def rotate_secret(
    endpoint_id: str,
    principal: EndpointsWrite,
    db: DB,
    body: Annotated[RotateSecretIn | None, Body()] = None,
) -> dict:
    """Issue a new secret. The old one keeps signing too (a second signature) for the grace period."""
    endpoint = _get_owned(db, principal, endpoint_id)
    grace = body.grace_period_seconds if body and body.grace_period_seconds is not None else None
    if grace is None:
        grace = get_settings().secret_rotation_grace_seconds
    now = datetime.now(UTC)
    # Only the secret being replaced is kept; a secret from an earlier rotation is dropped.
    endpoint.previous_secret_encrypted = endpoint.secret_encrypted if grace > 0 else None
    endpoint.previous_secret_expires_at = now + timedelta(seconds=grace) if grace > 0 else None
    endpoint.secret_encrypted = encrypt_secret(new_signing_secret())
    endpoint.updated_at = now
    audit.record(db, principal, "endpoint.secret_rotated", "endpoint", endpoint.id,
                 {"grace_period_seconds": grace})
    db.commit()
    return _secret_out(endpoint)
