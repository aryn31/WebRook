from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from app import audit, emailcodes, mailer, ratelimit
from app.clientip import client_ip
from app.config import get_settings
from app.deps import DB, Principal, SessionPrincipal, member_role
from app.errors import ApiError
from app.models import AccountMember, User, UserSession
from app.permissions import API_SCOPES, SESSION_ONLY
from app.schemas import (
    AccountOut,
    Credentials,
    ListOf,
    MeOut,
    PasswordChangeIn,
    PasswordChangeOut,
    RegisterIn,
    RegisterOut,
    SessionOut,
    SignedOutOut,
    SwitchAccountIn,
    UserEnvelope,
    UserOut,
    VerificationSentOut,
    VerifyEmailIn,
)
from app.security import hash_password, new_session_token, sha256_hex, verify_password

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _limit(request: Request, action: str, email: str) -> None:
    limit = get_settings().auth_rate_limit_per_minute
    ratelimit.enforce(f"auth:{action}:ip:{client_ip(request)}", limit)
    ratelimit.enforce(f"auth:{action}:email:{sha256_hex(email.lower())}", limit)


USER_AGENT_MAX = 512


def _new_session(db: DB, request: Request, user: User, account_id: str | None = None) -> str:
    """Add a session for ``user`` and return its token (only the hash is stored)."""
    token = new_session_token()
    now = datetime.now(UTC)
    db.add(
        UserSession(
            user_id=user.id,
            account_id=account_id,
            token_hash=sha256_hex(token),
            expires_at=now + timedelta(hours=get_settings().session_ttl_hours),
            ip_address=client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:USER_AGENT_MAX] or None,
            last_seen_at=now,
        )
    )
    return token


def _set_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        s.session_cookie_name,
        token,
        max_age=s.session_ttl_hours * 3600,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        path="/",
    )


def _start_session(db: DB, request: Request, response: Response, user: User, action: str) -> None:
    token = _new_session(db, request, user)
    audit.record(db, Principal(user=user, via="session", ip=client_ip(request)), action, "user", user.id)
    db.commit()
    _set_cookie(response, token)


@router.post("/register", status_code=201, response_model=RegisterOut)
def register(body: RegisterIn, request: Request, response: Response, db: DB) -> dict:
    email = body.email.lower()
    _limit(request, "register", email)
    existing = db.scalar(select(User).where(func.lower(User.email) == email))
    if existing is not None:
        if existing.email_verified_at is not None:
            raise ApiError(409, "An account with this email already exists.", code="email_taken")
        # Someone signed up with this email but never proved they own it, so the account can't have done anything.
        # Replace it: otherwise anyone could block the real owner from signing up.
        db.execute(delete(User).where(User.id == existing.id))
        db.flush()
    user = User(email=email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "An account with this email already exists.", code="email_taken") from None
    code = emailcodes.issue(db, user)
    _start_session(db, request, response, user, "auth.registered")
    return {"user": UserOut.model_validate(user), "verification_email_sent": _try_send(user.email, code)}


def _try_send(email: str, code: str) -> bool:
    try:
        emailcodes.send_verification(email, code)
        return True
    except mailer.MailError:
        return False


@router.post("/verify-email", response_model=UserEnvelope)
def verify_email(body: VerifyEmailIn, principal: SessionPrincipal, db: DB) -> dict:
    """Enter the code from the verification email. Unlocks the dashboard."""
    me = db.get(User, principal.actor.id)
    if me.email_verified_at is not None:
        return {"user": UserOut.model_validate(me)}
    ratelimit.enforce(f"auth:verify:user:{me.id}", get_settings().auth_rate_limit_per_minute)
    ok, left = emailcodes.check(db, me.id, body.code)
    if not ok:
        db.commit()  # keep the attempt count
        if left is None:
            raise ApiError(400, "This code has expired or been used too many times. Send a new one.",
                           code="code_expired")
        raise ApiError(400, f"That code isn't right. {left} attempt{'s' if left != 1 else ''} left.",
                       code="invalid_code", details={"attempts_left": left})
    me.email_verified_at = datetime.now(UTC)
    audit.record(db, _personal(principal), "auth.email_verified", "user", me.id)
    db.commit()
    return {"user": UserOut.model_validate(me)}


@router.post("/resend-verification", response_model=VerificationSentOut)
def resend_verification(principal: SessionPrincipal, db: DB) -> dict:
    """Email a new verification code. The previous code stops working."""
    s = get_settings()
    me = db.get(User, principal.actor.id)
    if me.email_verified_at is not None:
        raise ApiError(400, "Your email is already verified.", code="already_verified")
    last = emailcodes.last_sent_at(db, me.id, emailcodes.VERIFY_EMAIL)
    if last is not None:
        wait = s.email_code_resend_seconds - int((datetime.now(UTC) - last).total_seconds())
        if wait > 0:
            raise ApiError(429, f"Wait {wait} seconds before sending another code.", code="resend_too_soon",
                           headers={"Retry-After": str(wait)})
    ratelimit.enforce(f"auth:verify-send:user:{me.id}", s.email_codes_per_hour, window_seconds=3600)
    code = emailcodes.issue(db, me)
    db.commit()
    if not _try_send(me.email, code):
        raise ApiError(503, "We couldn't send the email. Try again in a minute.", code="email_failed")
    return {"sent_to": me.email, "resend_after_seconds": s.email_code_resend_seconds}


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


# --- Your security: password and sessions --------------------------------------
# These always act on the logged-in person, whichever account they're working in, and are recorded in their own
# account's audit log.

def _personal(principal: Principal) -> Principal:
    me = principal.actor
    return Principal(user=me, via="session", session=principal.session, actor=me, ip=principal.ip)


def _active_sessions(user_id: str):
    return (
        select(UserSession)
        .where(UserSession.user_id == user_id)
        .where(UserSession.revoked_at.is_(None))
        .where(UserSession.expires_at > datetime.now(UTC))
    )


def _sign_out_others(db: DB, principal: Principal, keep: str) -> int:
    q = (
        update(UserSession)
        .where(UserSession.user_id == principal.actor.id)
        .where(UserSession.revoked_at.is_(None))
        .where(UserSession.expires_at > datetime.now(UTC))
        .where(UserSession.id != keep)
        .values(revoked_at=datetime.now(UTC))
    )
    return db.execute(q).rowcount or 0


@router.post("/password", response_model=PasswordChangeOut)
def change_password(
    body: PasswordChangeIn, principal: SessionPrincipal, request: Request, response: Response, db: DB
) -> dict:
    """Change your password. Every other session is signed out, and this one gets a fresh token."""
    me = db.get(User, principal.actor.id)
    ratelimit.enforce(f"auth:password:user:{me.id}", get_settings().auth_rate_limit_per_minute)
    if not verify_password(me.password_hash, body.current_password):
        raise ApiError(400, "Your current password is incorrect.", code="invalid_current_password",
                       details={"field": "current_password"})
    if body.new_password == body.current_password:
        raise ApiError(400, "Choose a password different from your current one.", code="same_password",
                       details={"field": "new_password"})
    me.password_hash = hash_password(body.new_password)

    # Replace this session too, so a token copied before the change stops working.
    current = db.get(UserSession, principal.session.id)
    signed_out = _sign_out_others(db, principal, keep=current.id)
    current.revoked_at = datetime.now(UTC)
    token = _new_session(db, request, me, account_id=current.account_id)
    audit.record(db, _personal(principal), "auth.password_changed", "user", me.id,
                 {"signed_out_sessions": signed_out})
    db.commit()
    _set_cookie(response, token)
    return {"signed_out_sessions": signed_out}


@router.get("/sessions", response_model=ListOf[SessionOut])
def list_sessions(principal: SessionPrincipal, db: DB) -> dict:
    """Where you're logged in: every session that hasn't expired or been signed out, most recently used first."""
    rows = db.scalars(
        _active_sessions(principal.actor.id).order_by(
            func.coalesce(UserSession.last_seen_at, UserSession.created_at).desc()
        )
    ).all()
    current = principal.session.id
    return {
        "data": [
            SessionOut(
                id=r.id,
                created_at=r.created_at,
                last_seen_at=r.last_seen_at or r.created_at,
                expires_at=r.expires_at,
                ip_address=r.ip_address,
                user_agent=r.user_agent,
                current=r.id == current,
            )
            for r in rows
        ]
    }


@router.post("/sessions/sign-out-others", response_model=SignedOutOut)
def sign_out_others(principal: SessionPrincipal, db: DB) -> dict:
    """Sign out every session except this one."""
    n = _sign_out_others(db, principal, keep=principal.session.id)
    audit.record(db, _personal(principal), "auth.sessions_signed_out", "user", principal.actor.id,
                 {"signed_out_sessions": n})
    db.commit()
    return {"signed_out_sessions": n}


@router.delete("/sessions/{session_id}", status_code=204)
def sign_out_session(session_id: str, principal: SessionPrincipal, db: DB) -> Response:
    """Sign out one of your sessions. Signing out this session is the same as logging out."""
    session = db.scalar(_active_sessions(principal.actor.id).where(UserSession.id == session_id))
    if session is None:
        raise ApiError(404, "Session not found, or already signed out.", code="not_found")
    session.revoked_at = datetime.now(UTC)
    audit.record(db, _personal(principal), "auth.session_signed_out", "session", session.id)
    db.commit()
    out = Response(status_code=204)
    if session.id == principal.session.id:
        s = get_settings()
        out.delete_cookie(s.session_cookie_name, path="/", httponly=True, secure=s.cookie_secure, samesite="lax")
    return out
