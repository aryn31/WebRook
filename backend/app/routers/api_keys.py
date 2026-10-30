from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import select

from app.deps import DB, SessionPrincipal
from app.errors import not_found
from app.models import ApiKey
from app.schemas import ApiKeyCreated, ApiKeyEnvelope, ApiKeyIn, ApiKeyOut, ListOf
from app.security import new_api_key

router = APIRouter(prefix="/v1/api-keys", tags=["api keys"])


@router.get("", response_model=ListOf[ApiKeyOut])
def list_keys(principal: SessionPrincipal, db: DB) -> dict:
    keys = db.scalars(select(ApiKey).where(ApiKey.user_id == principal.user.id).order_by(ApiKey.id.desc())).all()
    return {"data": keys}


@router.post("", status_code=201, response_model=ApiKeyCreated)
def create_key(body: ApiKeyIn, principal: SessionPrincipal, db: DB) -> dict:
    full_key, prefix, key_hash = new_api_key()
    key = ApiKey(user_id=principal.user.id, name=body.name.strip(), prefix=prefix, key_hash=key_hash)
    db.add(key)
    db.commit()
    return {"api_key": key, "key": full_key}


@router.delete("/{key_id}", response_model=ApiKeyEnvelope)
def revoke_key(key_id: str, principal: SessionPrincipal, db: DB) -> dict:
    key = db.scalar(select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == principal.user.id))
    if key is None:
        raise not_found("API key")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        db.commit()
    return {"api_key": key}
