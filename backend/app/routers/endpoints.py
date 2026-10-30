from datetime import UTC, datetime

from fastapi import APIRouter, Response
from sqlalchemy import func, select, update

from app.config import get_settings
from app.deps import DB, CurrentPrincipal
from app.errors import ApiError, not_found
from app.models import Delivery, DeliveryStatus, Endpoint, EndpointSubscription
from app.pagination import Cursor, Limit, paginate
from app.schemas import EndpointCreated, EndpointIn, EndpointOut, EndpointPatch, Page, SigningSecret
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
        secret_encrypted=encrypt_secret(secret),
        subscriptions=[EndpointSubscription(event_type=t) for t in body.event_types],
    )
    db.add(endpoint)
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
    if "url" in fields and body.url is not None:
        endpoint.url = _check_url(body.url)
    if "description" in fields:
        endpoint.description = body.description
    if "event_types" in fields and body.event_types is not None:
        endpoint.subscriptions = [EndpointSubscription(event_type=t) for t in body.event_types]
    if "enabled" in fields and body.enabled is not None:
        if endpoint.enabled and not body.enabled:
            _cancel_unsent(db, endpoint.id, "Cancelled because the endpoint was disabled.")
        endpoint.enabled = body.enabled
    endpoint.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(endpoint)
    return endpoint


@router.delete("/{endpoint_id}", status_code=204)
def archive_endpoint(endpoint_id: str, principal: CurrentPrincipal, db: DB) -> Response:
    endpoint = _get_owned(db, principal, endpoint_id)
    endpoint.archived_at = datetime.now(UTC)
    endpoint.enabled = False
    _cancel_unsent(db, endpoint.id, "Cancelled because the endpoint was deleted.")
    db.commit()
    return Response(status_code=204)


@router.get("/{endpoint_id}/secret", response_model=SigningSecret)
def get_secret(endpoint_id: str, principal: CurrentPrincipal, db: DB) -> dict:
    endpoint = _get_owned(db, principal, endpoint_id)
    return {"signing_secret": decrypt_secret(endpoint.secret_encrypted)}


@router.post("/{endpoint_id}/rotate-secret", response_model=SigningSecret)
def rotate_secret(endpoint_id: str, principal: CurrentPrincipal, db: DB) -> dict:
    endpoint = _get_owned(db, principal, endpoint_id)
    secret = new_signing_secret()
    endpoint.secret_encrypted = encrypt_secret(secret)
    endpoint.updated_at = datetime.now(UTC)
    db.commit()
    return {"signing_secret": secret}
