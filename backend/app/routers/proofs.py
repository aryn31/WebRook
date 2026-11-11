"""Proof-of-delivery links: create, list and revoke them (dashboard and API), and the public proof page's data."""

import hashlib
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response
from sqlalchemy import func, select, update

from app import audit, proof, ratelimit
from app.clientip import client_ip
from app.deps import DB, DeliveriesRead, DeliveriesReplay
from app.errors import ApiError, not_found
from app.models import Delivery, DeliveryAttempt, ProofLink, User
from app.routers.deliveries import _owned
from app.schemas import ListOf, ProofLinkCreated, ProofLinkIn, ProofLinkOut, ProofPublicKey, ProofView
from app.security import sha256_hex
from app.worker.engine import build_body

router = APIRouter(prefix="/v1/deliveries", tags=["proof of delivery"])
public_router = APIRouter(prefix="/v1/proof", tags=["proof of delivery"])

MAX_ACTIVE_PER_DELIVERY = 20
CREATES_PER_MINUTE = 30
VIEWS_PER_MINUTE = 60


def _now() -> datetime:
    return datetime.now(UTC)


def _active(p: ProofLink, now: datetime) -> bool:
    return p.revoked_at is None and p.expires_at > now


def _out(p: ProofLink, email: str | None) -> dict:
    return {
        "id": p.id, "delivery_id": p.delivery_id, "include_body": p.include_body, "sender_name": p.sender_name,
        "created_by_email": email, "created_at": p.created_at, "expires_at": p.expires_at,
        "revoked_at": p.revoked_at, "view_count": p.view_count, "last_viewed_at": p.last_viewed_at,
        "active": _active(p, _now()),
    }


@router.post("/{delivery_id}/proofs", status_code=201, response_model=ProofLinkCreated)
def create_proof(delivery_id: str, body: ProofLinkIn, principal: DeliveriesReplay, db: DB) -> dict:
    """Create a public proof-of-delivery page for this delivery. Anyone with the link can open it until it expires
    or is revoked, so share it only with the people who need it."""
    d = _owned(db, principal, delivery_id)
    ratelimit.enforce(f"proof_create:{principal.user.id}", CREATES_PER_MINUTE)
    now = _now()
    active = db.scalar(select(func.count()).select_from(ProofLink).where(
        ProofLink.delivery_id == d.id, ProofLink.revoked_at.is_(None), ProofLink.expires_at > now))
    if active >= MAX_ACTIVE_PER_DELIVERY:
        raise ApiError(409, f"This delivery already has {MAX_ACTIVE_PER_DELIVERY} active proof links. "
                            "Revoke one first.", code="too_many_proof_links")
    token = proof.new_token()
    p = ProofLink(user_id=principal.user.id, delivery_id=d.id, token_hash=sha256_hex(token),
                  include_body=body.include_body, sender_name=body.sender_name,
                  created_by_user_id=principal.actor_id, created_at=now,
                  expires_at=now + timedelta(days=body.expires_in_days))
    db.add(p)
    db.flush()
    audit.record(db, principal, "delivery.proof_shared", "delivery", d.id,
                 {"proof_id": p.id, "include_body": p.include_body, "expires_in_days": body.expires_in_days})
    db.commit()
    db.refresh(p)
    email = db.scalar(select(User.email).where(User.id == p.created_by_user_id)) if p.created_by_user_id else None
    return {**_out(p, email), "url": proof.proof_url(token), "token": token}


@router.get("/{delivery_id}/proofs", response_model=ListOf[ProofLinkOut])
def list_proofs(delivery_id: str, principal: DeliveriesRead, db: DB) -> dict:
    _owned(db, principal, delivery_id)
    rows = db.execute(
        select(ProofLink, User.email)
        .outerjoin(User, User.id == ProofLink.created_by_user_id)
        .where(ProofLink.delivery_id == delivery_id, ProofLink.user_id == principal.user.id)
        .order_by(ProofLink.id.desc())
    ).all()
    return {"data": [_out(p, email) for p, email in rows]}


@router.delete("/{delivery_id}/proofs/{proof_id}", status_code=204)
def revoke_proof(delivery_id: str, proof_id: str, principal: DeliveriesReplay, db: DB) -> Response:
    _owned(db, principal, delivery_id)
    p = db.scalar(select(ProofLink).where(ProofLink.id == proof_id, ProofLink.delivery_id == delivery_id,
                                          ProofLink.user_id == principal.user.id))
    if p is None:
        raise not_found("Proof link")
    if p.revoked_at is None:
        p.revoked_at = _now()
        audit.record(db, principal, "delivery.proof_revoked", "delivery", delivery_id, {"proof_id": p.id})
        db.commit()
    return Response(status_code=204)


# --- Public -------------------------------------------------------------------

@public_router.get("/public-key", response_model=ProofPublicKey)
def get_public_key() -> dict:
    """The Ed25519 public key that signs proof receipts."""
    key_id, key = proof.public_key()
    return {"key_id": key_id, "public_key": key}


@public_router.get("/{token}", response_model=ProofView)
def view_proof(token: str, request: Request, db: DB) -> dict:
    """A proof-of-delivery page's data. No login: the token is the permission."""
    ratelimit.enforce(f"proof_view:{client_ip(request)}", VIEWS_PER_MINUTE)
    p = None
    if token.startswith(proof.TOKEN_PREFIX) and len(token) <= 64:
        p = db.scalar(select(ProofLink).where(ProofLink.token_hash == sha256_hex(token)))
    if p is None:
        raise ApiError(404, "This proof link doesn't exist. Check you copied the whole link.",
                       code="proof_not_found")
    now = _now()
    if p.revoked_at is not None:
        raise ApiError(410, "The sender has turned this proof link off.", code="proof_revoked")
    if p.expires_at <= now:
        raise ApiError(410, "This proof link has expired. Ask the sender for a new one.", code="proof_expired")
    d = db.scalar(select(Delivery).where(Delivery.id == p.delivery_id, Delivery.user_id == p.user_id))
    if d is None:
        raise ApiError(404, "This delivery no longer exists.", code="proof_not_found")

    db.execute(update(ProofLink).where(ProofLink.id == p.id)
               .values(view_count=ProofLink.view_count + 1, last_viewed_at=now))
    db.commit()

    attempts = db.scalars(select(DeliveryAttempt).where(DeliveryAttempt.delivery_id == d.id)
                          .order_by(DeliveryAttempt.attempt_number, DeliveryAttempt.started_at)).all()
    e = d.event
    raw = build_body(e.id, e.event_type, e.created_at, e.payload)
    body_sha256 = "sha256:" + hashlib.sha256(raw).hexdigest()
    attempts_out = [
        {"attempt_number": a.attempt_number, "started_at": a.started_at, "duration_ms": a.duration_ms,
         "response_status": a.response_status, "error": a.error, "success": a.success}
        for a in attempts if a.completed_at is not None
    ]
    facts = {
        "version": 1,
        "issuer": "HookFlow",
        "proof_id": p.id,
        "sender_name": p.sender_name,
        "delivery_id": d.id,
        "event_id": e.id,
        "event_type": e.event_type,
        "event_created_at": e.created_at,
        "endpoint_url": proof.public_url(d.endpoint.url),
        "status": d.status,
        "delivered_at": d.delivered_at,
        "body_sha256": body_sha256,
        "attempts": attempts_out,
        "checked_at": now,
    }
    return {
        **{k: v for k, v in facts.items() if k not in ("version", "issuer")},
        "body": raw.decode() if p.include_body else None,
        "expires_at": p.expires_at,
        "receipt": proof.sign_receipt(facts),
    }
