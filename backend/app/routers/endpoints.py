from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Body, Response
from sqlalchemy import func, select, update

from app import audit
from app.config import get_settings
from app.deps import DB, CurrentPrincipal
from app.errors import ApiError, not_found
from app.models import Delivery, DeliveryStatus, Endpoint, EndpointSubscription
from app.pagination import Cursor, Limit, paginate
from app.schemas import EndpointCreated, EndpointIn, EndpointOut, EndpointPatch, Page, RotateSecretIn, SigningSecret
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


@router.get("", response_model=Page[EndpointOut])
def list_endpoints(principal: CurrentPrincipal, db: DB, limit: Limit = 25, cursor: Cursor = None) -> dict:
    stmt = select(Endpoint).where(Endpoint.user_id == principal.user.id, Endpoint.archived_at.is_(None))
    data, next_cursor = paginate(db, stmt, Endpoint.id, limit, cursor)
    return {"data": data, "next_cursor": next_cursor}


@router.post("", status_code=201, response_model=EndpointCreated)
def create_endpoint(body: EndpointIn, principal: CurrentPrincipal, db: DB) -> dict:
    url = _check_url(body.url)
    count = db.scalar(
        select(func.count()).where(Endpoint.user_id == principal.user.id, Endpoint.archived_at.is_(None))
    )
    limit = get_settings().max_endpoints_per_account
    if (count or 0) >= limit:
        raise ApiError(409, f"Accounts can have at most {limit} endpoints.", code="endpoint_limit_reached")

    secret = new_signing_secret()
    endpoint = Endpoint(
        user_id=principal.user.id,
        url=url,
        description=body.description,
        enabled=body.enabled,
        max_attempts=body.max_attempts or get_settings().delivery_max_attempts,
        secret_encrypted=encrypt_secret(secret),
        subscriptions=[EndpointSubscription(event_type=t) for t in body.event_types],
    )
    db.add(endpoint)
    db.flush()
    audit.record(db, principal, "endpoint.created", "endpoint", endpoint.id,
                 {"url": url, "event_types": body.event_types, "max_attempts": endpoint.max_attempts})
    db.commit()
    db.refresh(endpoint)
    return {**EndpointOut.model_validate(endpoint).model_dump(), "signing_secret": secret}


@router.get("/{endpoint_id}", response_model=EndpointOut)
def get_endpoint(endpoint_id: str, principal: CurrentPrincipal, db: DB) -> Endpoint:
    return _get_owned(db, principal, endpoint_id)


@router.patch("/{endpoint_id}", response_model=EndpointOut)
def update_endpoint(endpoint_id: str, body: EndpointPatch, principal: CurrentPrincipal, db: DB) -> Endpoint:
    endpoint = _get_owned(db, principal, endpoint_id)
    fields = body.model_fields_set
    changes: dict = {}
    if "url" in fields and body.url is not None:
        url = _check_url(body.url)
        if url != endpoint.url:
            changes["url"] = {"from": endpoint.url, "to": url}
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
def archive_endpoint(endpoint_id: str, principal: CurrentPrincipal, db: DB) -> Response:
    endpoint = _get_owned(db, principal, endpoint_id)
    endpoint.archived_at = datetime.now(UTC)
    endpoint.enabled = False
    _cancel_unsent(db, endpoint.id, "Cancelled because the endpoint was deleted.")
    audit.record(db, principal, "endpoint.archived", "endpoint", endpoint.id, {"url": endpoint.url})
    db.commit()
    return Response(status_code=204)


def _secret_out(endpoint: Endpoint) -> dict:
    expires = endpoint.previous_secret_expires_at
    return {
        "signing_secret": decrypt_secret(endpoint.secret_encrypted),
        "previous_secret_expires_at": expires if expires and expires > datetime.now(UTC) else None,
    }


@router.get("/{endpoint_id}/secret", response_model=SigningSecret)
def get_secret(endpoint_id: str, principal: CurrentPrincipal, db: DB) -> dict:
    endpoint = _get_owned(db, principal, endpoint_id)
    audit.record(db, principal, "endpoint.secret_viewed", "endpoint", endpoint.id)
    db.commit()
    return _secret_out(endpoint)


@router.post("/{endpoint_id}/rotate-secret", response_model=SigningSecret)
def rotate_secret(
    endpoint_id: str,
    principal: CurrentPrincipal,
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
