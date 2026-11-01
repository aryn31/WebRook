from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import Depends, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.clientip import client_ip
from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import ApiKey, User, UserSession
from app.security import constant_time_equals, parse_api_key_prefix, sha256_hex

DB = Annotated[Session, Depends(get_db)]


@dataclass
class Principal:
    user: User
    via: Literal["session", "api_key"]
    session: UserSession | None = None
    api_key: ApiKey | None = None
    ip: str | None = None


def _from_api_key(db: Session, raw_key: str) -> Principal | None:
    prefix = parse_api_key_prefix(raw_key)
    if prefix is None:
        return None
    key = db.scalar(select(ApiKey).where(ApiKey.prefix == prefix))
    if key is None or key.revoked_at is not None:
        return None
    if not constant_time_equals(key.key_hash, sha256_hex(raw_key)):
        return None
    now = datetime.now(UTC)
    # Only write last_used_at once a minute per key to avoid a DB write on every request.
    if key.last_used_at is None or now - key.last_used_at > timedelta(minutes=1):
        db.execute(update(ApiKey).where(ApiKey.id == key.id).values(last_used_at=now))
        db.commit()
    return Principal(user=key.user, via="api_key", api_key=key)


def _from_session(db: Session, token: str) -> Principal | None:
    session = db.scalar(select(UserSession).where(UserSession.token_hash == sha256_hex(token)))
    if session is None or session.revoked_at is not None or session.expires_at <= datetime.now(UTC):
        return None
    return Principal(user=session.user, via="session", session=session)


def get_principal(request: Request, db: DB) -> Principal:
    principal = _authenticate(request, db)
    principal.ip = client_ip(request)
    return principal


def _authenticate(request: Request, db: Session) -> Principal:
    auth = request.headers.get("authorization")
    if auth:
        scheme, _, token = auth.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise ApiError(401, "Use 'Authorization: Bearer <api key>'.")
        principal = _from_api_key(db, token.strip())
        if principal is None:
            raise ApiError(401, "Invalid or revoked API key.")
        return principal

    cookie = request.cookies.get(get_settings().session_cookie_name)
    if cookie:
        principal = _from_session(db, cookie)
        if principal is not None:
            return principal
    raise ApiError(401, "Authentication required.")


def get_session_principal(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
    if principal.via != "session":
        raise ApiError(403, "This operation is only available from the dashboard.")
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
SessionPrincipal = Annotated[Principal, Depends(get_session_principal)]
