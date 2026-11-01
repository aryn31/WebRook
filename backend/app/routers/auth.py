from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import audit, ratelimit
from app.clientip import client_ip
from app.config import get_settings
from app.deps import DB, Principal, SessionPrincipal
from app.errors import ApiError
from app.models import User, UserSession
from app.schemas import Credentials, RegisterIn, UserEnvelope, UserOut
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


@router.get("/me", response_model=UserEnvelope)
def me(principal: SessionPrincipal) -> dict:
    return {"user": UserOut.model_validate(principal.user)}
