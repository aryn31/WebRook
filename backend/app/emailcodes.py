"""Short codes emailed to users, to prove they own their email address.

Codes are 6 digits, so only a keyed hash is stored (a plain hash of a million possibilities is easy to reverse).
Each code expires after a few minutes and allows a few wrong guesses; then a new one has to be sent.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import email_templates, mailer
from app.config import get_settings
from app.models import EmailCode, User

VERIFY_EMAIL = "verify_email"
RESET_PASSWORD = "reset_password"


def _hash(user_id: str, purpose: str, code: str) -> str:
    key = get_settings().secret_encryption_key.encode()
    return hmac.new(key, f"{purpose}:{user_id}:{code}".encode(), hashlib.sha256).hexdigest()


def open_code(db: Session, user_id: str, purpose: str) -> EmailCode | None:
    """The newest code that is unused and unexpired, or None."""
    return db.scalar(
        select(EmailCode)
        .where(EmailCode.user_id == user_id, EmailCode.purpose == purpose)
        .where(EmailCode.used_at.is_(None), EmailCode.expires_at > datetime.now(UTC))
        .order_by(EmailCode.created_at.desc())
        .limit(1)
    )


def last_sent_at(db: Session, user_id: str, purpose: str) -> datetime | None:
    return db.scalar(
        select(EmailCode.created_at)
        .where(EmailCode.user_id == user_id, EmailCode.purpose == purpose)
        .order_by(EmailCode.created_at.desc())
        .limit(1)
    )


def issue(db: Session, user: User, purpose: str = VERIFY_EMAIL) -> str:
    """Replace any open code with a new one, and return it. The caller commits, then emails it."""
    now = datetime.now(UTC)
    db.execute(
        update(EmailCode)
        .where(EmailCode.user_id == user.id, EmailCode.purpose == purpose, EmailCode.used_at.is_(None))
        .values(expires_at=now)
    )
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(
        EmailCode(
            user_id=user.id,
            purpose=purpose,
            code_hash=_hash(user.id, purpose, code),
            attempts=0,
            created_at=now,
            expires_at=now + timedelta(minutes=get_settings().email_code_ttl_minutes),
        )
    )
    return code


def check(db: Session, user_id: str, code: str, purpose: str = VERIFY_EMAIL) -> tuple[bool, int | None]:
    """Check a code. Returns (ok, attempts_left); attempts_left is None when there's no usable code.

    A right code is marked used. A wrong one counts as an attempt; the last allowed attempt closes the code.
    The caller commits.
    """
    row = open_code(db, user_id, purpose)
    max_attempts = get_settings().email_code_max_attempts
    if row is None or row.attempts >= max_attempts:
        return False, None
    if hmac.compare_digest(row.code_hash, _hash(user_id, purpose, code.strip())):
        row.used_at = datetime.now(UTC)
        return True, None
    row.attempts += 1
    left = max_attempts - row.attempts
    if left <= 0:
        row.expires_at = datetime.now(UTC)
        return False, None
    return False, left


def _send(template, to: str, code: str) -> None:
    s = get_settings()
    subject, text, html = template(code=code, email=to, minutes=s.email_code_ttl_minutes,
                                   app_url=s.app_url.rstrip("/"))
    mailer.send(to, subject, text, html)


def send_verification(to: str, code: str) -> None:
    """Raises mailer.MailError if it couldn't be sent."""
    _send(email_templates.verification_code, to, code)


def send_password_reset(to: str, code: str) -> None:
    """Raises mailer.MailError if it couldn't be sent."""
    _send(email_templates.password_reset_code, to, code)
