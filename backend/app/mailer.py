"""Sending email. Four backends, picked by MAIL_BACKEND:

- ``console``: logs the email instead of sending it (local development).
- ``smtp``: any SMTP server with STARTTLS (e.g. Gmail with an app password). Some hosts block SMTP ports.
- ``gmail``: the Gmail API over HTTPS, sending from your own Gmail account. Works where SMTP is blocked (such as
  Render's free plan). Get the refresh token with ``backend/scripts/gmail_token.py``.
- ``brevo``: Brevo's HTTPS API.
"""

import base64
import logging
import smtplib
import threading
import time
from email.message import EmailMessage

import httpx

from app.config import get_settings

log = logging.getLogger("hookflow.mail")

TIMEOUT_SECONDS = 10


class MailError(Exception):
    """The email couldn't be sent. The message is safe to log but not meant for end users."""


def send(to: str, subject: str, text: str, html: str | None = None) -> None:
    """Send an email with a plain-text body and, optionally, an HTML version of the same content."""
    s = get_settings()
    try:
        if s.mail_backend == "smtp":
            _smtp(to, subject, text, html)
        elif s.mail_backend == "gmail":
            _gmail(to, subject, text, html)
        elif s.mail_backend == "brevo":
            _brevo(to, subject, text, html)
        else:
            log.warning("Email not sent (MAIL_BACKEND=console). To: %s | Subject: %s\n%s", to, subject, text)
    except MailError:
        raise
    except Exception as e:  # network errors, auth failures, timeouts
        log.error("Email to %s failed: %s", to, e)
        raise MailError(str(e)) from e


def _message(to: str, subject: str, text: str, html: str | None = None) -> EmailMessage:
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = f"{s.mail_from_name} <{s.mail_from_email}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def _smtp(to: str, subject: str, text: str, html: str | None = None) -> None:
    s = get_settings()
    msg = _message(to, subject, text, html)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=TIMEOUT_SECONDS) as smtp:
        smtp.starttls()
        if s.smtp_username:
            smtp.login(s.smtp_username, s.smtp_password)
        smtp.send_message(msg)


def _brevo(to: str, subject: str, text: str, html: str | None = None) -> None:
    s = get_settings()
    r = httpx.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": s.brevo_api_key, "accept": "application/json"},
        json={
            "sender": {"name": s.mail_from_name, "email": s.mail_from_email},
            "to": [{"email": to}],
            "subject": subject,
            "textContent": text,
            **({"htmlContent": html} if html else {}),
        },
        timeout=TIMEOUT_SECONDS,
    )
    if r.status_code >= 300:
        raise MailError(f"Brevo returned HTTP {r.status_code}: {r.text[:300]}")


# --- Gmail API ----------------------------------------------------------------
# A refresh token is exchanged for a short-lived access token, which is reused until shortly before it expires.

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

_token_lock = threading.Lock()
_token: tuple[str, float] | None = None  # (access token, monotonic time it stops being reused)


def _gmail_access_token(force_refresh: bool = False) -> str:
    global _token
    with _token_lock:
        if not force_refresh and _token is not None and time.monotonic() < _token[1]:
            return _token[0]
        s = get_settings()
        r = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": s.gmail_client_id,
                "client_secret": s.gmail_client_secret,
                "refresh_token": s.gmail_refresh_token,
            },
            timeout=TIMEOUT_SECONDS,
        )
        if r.status_code != 200:
            # invalid_grant usually means the token was revoked or expired: run scripts/gmail_token.py again.
            raise MailError(f"Google token refresh failed (HTTP {r.status_code}): {r.text[:300]}")
        body = r.json()
        _token = (body["access_token"], time.monotonic() + max(int(body.get("expires_in", 3600)) - 60, 0))
        return _token[0]


def _gmail(to: str, subject: str, text: str, html: str | None = None) -> None:
    raw = base64.urlsafe_b64encode(_message(to, subject, text, html).as_bytes()).decode()
    for attempt in range(2):
        token = _gmail_access_token(force_refresh=attempt > 0)
        r = httpx.post(GMAIL_SEND_URL, headers={"Authorization": f"Bearer {token}"}, json={"raw": raw},
                       timeout=TIMEOUT_SECONDS)
        if r.status_code == 401 and attempt == 0:
            continue  # access token revoked early: get a fresh one and try once more
        if r.status_code >= 300:
            raise MailError(f"Gmail API returned HTTP {r.status_code}: {r.text[:300]}")
        return
