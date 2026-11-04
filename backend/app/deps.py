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
from app.models import AccountMember, ApiKey, User, UserSession
from app.permissions import key_permissions, role_permissions
from app.security import constant_time_equals, parse_api_key_prefix, sha256_hex

DB = Annotated[Session, Depends(get_db)]


@dataclass
class Principal:
    """Who is calling, and in which account.

    ``user`` is the *account* being worked in (its owner's user row). All data is scoped by ``user.id``.
    ``actor`` is the person acting: the logged-in user, or the creator of the API key. They differ when a
    team member works in someone else's account.
    """

    user: User
    via: Literal["session", "api_key"]
    session: UserSession | None = None
    api_key: ApiKey | None = None
    ip: str | None = None
    actor: User | None = None
    role: str = "owner"
    permissions: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.actor is None and self.via == "session":
            self.actor = self.user
        if not self.permissions and self.via == "session":
            self.permissions = role_permissions(self.role)

    @property
    def actor_id(self) -> str | None:
        return self.actor.id if self.actor else None


def member_role(db: Session, account_id: str, user_id: str) -> str | None:
    """The user's role in the account, or None if they have no access."""
    if account_id == user_id:
        return "owner"
    return db.scalar(
        select(AccountMember.role).where(AccountMember.account_id == account_id, AccountMember.user_id == user_id)
    )


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
    actor = db.get(User, key.created_by_user_id) if key.created_by_user_id else None
    return Principal(user=key.user, via="api_key", api_key=key, actor=actor, role="api_key",
                     permissions=key_permissions(key.scopes))


def _from_session(db: Session, token: str) -> Principal | None:
    session = db.scalar(select(UserSession).where(UserSession.token_hash == sha256_hex(token)))
    if session is None or session.revoked_at is not None or session.expires_at <= datetime.now(UTC):
        return None
    me = session.user
    account, role = me, "owner"
    if session.account_id and session.account_id != me.id:
        team_role = member_role(db, session.account_id, me.id)
        team = db.get(User, session.account_id) if team_role else None
        if team is not None:
            account, role = team, team_role
        # Otherwise they were removed from that team: fall back to their own account.
    return Principal(user=account, via="session", session=session, actor=me, role=role)


SESSION_SEEN_INTERVAL = timedelta(minutes=5)


# The only routes a logged-in person can use before verifying their email.
UNVERIFIED_ALLOWED = frozenset({
    "/v1/auth/me", "/v1/auth/logout", "/v1/auth/verify-email", "/v1/auth/resend-verification",
})


def get_principal(request: Request, db: DB) -> Principal:
    principal = _authenticate(request, db)
    principal.ip = client_ip(request)
    if principal.session is not None:
        _touch_session(db, principal.session, principal.ip)
        if principal.actor.email_verified_at is None and request.url.path not in UNVERIFIED_ALLOWED:
            raise ApiError(403, "Verify your email address first. We sent a code to " + principal.actor.email + ".",
                           code="email_unverified")
    return principal


def _touch_session(db: Session, session: UserSession, ip: str) -> None:
    """Record when and from where a session was last used, at most every few minutes, for the Security page."""
    now = datetime.now(UTC)
    if session.last_seen_at is not None and now - session.last_seen_at < SESSION_SEEN_INTERVAL:
        return
    db.execute(update(UserSession).where(UserSession.id == session.id).values(last_seen_at=now, ip_address=ip))
    db.commit()


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


def check(principal: Principal, permission: str) -> None:
    if permission in principal.permissions:
        return
    if principal.via == "api_key":
        raise ApiError(403, f"This API key doesn't have the '{permission}' scope.", code="insufficient_scope",
                       details={"required_scope": permission})
    raise ApiError(403, f"Your role ({principal.role}) can't do this. Ask an account admin.",
                   code="forbidden", details={"required_permission": permission})


def require(permission: str, session_only: bool = False):
    """Dependency: the caller, after checking they have ``permission``."""

    def dep(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if session_only and principal.via != "session":
            raise ApiError(403, "This operation is only available from the dashboard.")
        check(principal, permission)
        return principal

    return Depends(dep)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
SessionPrincipal = Annotated[Principal, Depends(get_session_principal)]

EventsRead = Annotated[Principal, require("events:read")]
EventsWrite = Annotated[Principal, require("events:write")]
DeliveriesRead = Annotated[Principal, require("deliveries:read")]
DeliveriesReplay = Annotated[Principal, require("deliveries:replay")]
EndpointsRead = Annotated[Principal, require("endpoints:read")]
EndpointsWrite = Annotated[Principal, require("endpoints:write")]
AuditRead = Annotated[Principal, require("audit:read")]
KeysManage = Annotated[Principal, require("api_keys:manage", session_only=True)]
TeamManage = Annotated[Principal, require("team:manage", session_only=True)]
