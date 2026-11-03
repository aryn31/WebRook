from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import select

from app import audit
from app.deps import DB, KeysManage
from app.errors import ApiError, not_found
from app.models import ApiKey
from app.permissions import API_SCOPES, key_permissions
from app.schemas import ApiKeyCreated, ApiKeyEnvelope, ApiKeyIn, ApiKeyOut, ListOf, ScopeOut
from app.security import new_api_key

router = APIRouter(prefix="/v1/api-keys", tags=["api keys"])

SCOPE_DESCRIPTIONS = {
    "events:write": "Send events.",
    "events:read": "Read events, stats and usage.",
    "deliveries:read": "Read deliveries and their attempts.",
    "deliveries:replay": "Replay deliveries, one at a time or in bulk.",
    "endpoints:read": "Read endpoints (not their signing secrets).",
    "endpoints:write": "Create, change and delete endpoints; view and rotate signing secrets.",
    "audit:read": "Read the audit log.",
}


def key_out(key: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        id=key.id, name=key.name, prefix=key.prefix,
        scopes=[s for s in API_SCOPES if s in key_permissions(key.scopes)],
        created_by_user_id=key.created_by_user_id, created_at=key.created_at,
        last_used_at=key.last_used_at, revoked_at=key.revoked_at,
    )


@router.get("/scopes", response_model=ListOf[ScopeOut])
def list_scopes(principal: KeysManage) -> dict:
    """Scopes an API key can have. Only the ones your role allows can be given to a new key."""
    return {"data": [{"scope": s, "description": SCOPE_DESCRIPTIONS[s]} for s in API_SCOPES]}


@router.get("", response_model=ListOf[ApiKeyOut])
def list_keys(principal: KeysManage, db: DB) -> dict:
    keys = db.scalars(select(ApiKey).where(ApiKey.user_id == principal.user.id).order_by(ApiKey.id.desc())).all()
    return {"data": [key_out(k) for k in keys]}


@router.post("", status_code=201, response_model=ApiKeyCreated)
def create_key(body: ApiKeyIn, principal: KeysManage, db: DB) -> dict:
    allowed = [s for s in API_SCOPES if s in principal.permissions]
    scopes = allowed if body.scopes is None else body.scopes
    beyond = [s for s in scopes if s not in allowed]
    if beyond:
        raise ApiError(403, f"Your role ({principal.role}) can't create a key with: {', '.join(beyond)}.",
                       code="forbidden", details={"scopes": beyond})
    full_key, prefix, key_hash = new_api_key()
    key = ApiKey(user_id=principal.user.id, name=body.name.strip(), prefix=prefix, key_hash=key_hash,
                 scopes=scopes, created_by_user_id=principal.actor_id)
    db.add(key)
    db.flush()
    audit.record(db, principal, "api_key.created", "api_key", key.id,
                 {"name": key.name, "prefix": prefix, "scopes": scopes})
    db.commit()
    db.refresh(key)
    return {"api_key": key_out(key), "key": full_key}


@router.delete("/{key_id}", response_model=ApiKeyEnvelope)
def revoke_key(key_id: str, principal: KeysManage, db: DB) -> dict:
    key = db.scalar(select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == principal.user.id))
    if key is None:
        raise not_found("API key")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        audit.record(db, principal, "api_key.revoked", "api_key", key.id, {"name": key.name, "prefix": key.prefix})
        db.commit()
    return {"api_key": key_out(key)}
