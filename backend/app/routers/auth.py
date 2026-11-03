from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import audit, ratelimit
from app.clientip import client_ip
from app.config import get_settings
from app.deps import DB, Principal, SessionPrincipal, member_role
from app.errors import ApiError
from app.models import AccountMember, User, UserSession
from app.permissions import API_SCOPES, SESSION_ONLY
from app.schemas import AccountOut, Credentials, MeOut, RegisterIn, SwitchAccountIn, UserEnvelope, UserOut
from app.security import hash_password, new_session_token, sha256_hex, verify_password

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _limit(request: Request, action: str, email: str) -> None:
    limit = get_settings().auth_rate_limit_per_minute
    ratelimit.enforce(f"auth:{action}:ip:{client_ip(request)}", limit)
    ratelimit.enforce(f"auth:{action}:email:{sha256_hex(email.lower())}", limit)


def _start_session(db: DB, request: Request, response: Response, user: User, action: str) -> None:
    s = get_settings()
    token = new_session_token()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=sha256_hex(token),
            expires_at=datetime.now(UTC) + timedelta(hours=s.session_ttl_hours),
        )
    )
    audit.record(db, Principal(user=user, via="session", ip=client_ip(request)), action, "user", user.id)
    db.commit()
    response.set_cookie(
        s.session_cookie_name,
        token,
        max_age=s.session_ttl_hours * 3600,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/register", status_code=201, response_model=UserEnvelope)
def register(body: RegisterIn, request: Request, response: Response, db: DB) -> dict:
    email = body.email.lower()
    _limit(request, "register", email)
    user = User(email=email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "An account with this email already exists.", code="email_taken") from None
    _start_session(db, request, response, user, "auth.registered")
    return {"user": UserOut.model_validate(user)}


@router.post("/login", response_model=UserEnvelope)
def login(body: Credentials, request: Request, response: Response, db: DB) -> dict:
    email = body.email.lower()
    _limit(request, "login", email)
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if not verify_password(user.password_hash if user else None, body.password) or user is None:
        raise ApiError(401, "Incorrect email or password.", code="invalid_credentials")
    _start_session(db, request, response, user, "auth.login")
    return {"user": UserOut.model_validate(user)}


@router.post("/logout", status_code=204)
def logout(principal: SessionPrincipal, response: Response, db: DB) -> Response:
    assert principal.session is not None
    session = db.get(UserSession, principal.session.id)
    if session is not None:
        session.revoked_at = datetime.now(UTC)
        db.commit()
    s = get_settings()
    out = Response(status_code=204)
    out.delete_cookie(s.session_cookie_name, path="/", httponly=True, secure=s.cookie_secure, samesite="lax")
    return out


def _accounts(db: DB, me: User) -> list[AccountOut]:
    own = AccountOut(id=me.id, owner_email=me.email, role="owner", personal=True)
    teams = db.execute(
        select(AccountMember.account_id, AccountMember.role, User.email)
        .join(User, User.id == AccountMember.account_id)
        .where(AccountMember.user_id == me.id)
        .order_by(User.email)
    ).all()
    return [own, *(AccountOut(id=a, owner_email=e, role=r, personal=False) for a, r, e in teams)]


def _me(db: DB, principal: Principal) -> dict:
    accounts = _accounts(db, principal.actor)
    current = next(a for a in accounts if a.id == principal.user.id)
    order = API_SCOPES + SESSION_ONLY
    return {
        "user": UserOut.model_validate(principal.actor),
        "account": current,
        "permissions": [p for p in order if p in principal.permissions],
        "accounts": accounts,
    }


@router.get("/me", response_model=MeOut)
def me(principal: SessionPrincipal, db: DB) -> dict:
    return _me(db, principal)


@router.post("/switch-account", response_model=MeOut)
def switch_account(body: SwitchAccountIn, principal: SessionPrincipal, db: DB) -> dict:
    """Work in another account: your own, or a team you belong to. Applies to this session only."""
    me = principal.actor
    role = member_role(db, body.account_id, me.id)
    if role is None:
        raise ApiError(404, "Account not found, or you're not a member.", code="not_found")
    session = db.get(UserSession, principal.session.id)
    session.account_id = None if body.account_id == me.id else body.account_id
    db.commit()
    account = db.get(User, body.account_id)
    return _me(db, Principal(user=account, via="session", session=session, actor=me, role=role, ip=principal.ip))
