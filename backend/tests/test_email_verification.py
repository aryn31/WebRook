"""Email verification: a code is emailed at sign-up, and nothing works until it's entered."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app import mailer
from app.db import SessionLocal
from app.models import AuditLog, EmailCode, User
from tests.conftest import last_code

PASSWORD = "correct-horse-battery"


def register(client: TestClient, email: str = "a@example.com", password: str = PASSWORD):
    return client.post("/v1/auth/register", json={"email": email, "password": password})


def new_client() -> TestClient:
    from app.main import app

    return TestClient(app)


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


def test_register_emails_a_code_and_locks_the_dashboard(client, mail):
    r = register(client)
    assert r.status_code == 201
    assert r.json()["user"]["email_verified"] is False
    assert r.json()["verification_email_sent"] is True
    assert mail[-1]["to"] == "a@example.com"
    code = last_code("a@example.com")
    assert code in mail[-1]["subject"]
    # Plain text and HTML versions, both with the code and a link back to the dashboard.
    assert "/verify-email" in mail[-1]["text"]
    assert code in mail[-1]["html"] and "/verify-email" in mail[-1]["html"]

    me = client.get("/v1/auth/me")
    assert me.status_code == 200 and me.json()["user"]["email_verified"] is False
    for method, path in [("GET", "/v1/endpoints"), ("GET", "/v1/events"), ("POST", "/v1/api-keys"),
                         ("GET", "/v1/auth/sessions"), ("GET", "/v1/team/members")]:
        r = client.request(method, path, json={"name": "k"} if method == "POST" else None)
        assert r.status_code == 403, path
        assert r.json()["error"]["code"] == "email_unverified"


def test_right_code_unlocks(client):
    register(client)
    r = client.post("/v1/auth/verify-email", json={"code": last_code("a@example.com")})
    assert r.status_code == 200
    assert r.json()["user"]["email_verified"] is True
    assert client.get("/v1/endpoints").status_code == 200
    assert client.get("/v1/auth/me").json()["user"]["email_verified"] is True
    with SessionLocal() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "auth.email_verified")) is not None
    # Verifying again is harmless.
    assert client.post("/v1/auth/verify-email", json={"code": "000000"}).status_code == 200


def test_code_with_spaces_is_accepted(client):
    register(client)
    code = last_code("a@example.com")
    assert client.post("/v1/auth/verify-email", json={"code": f" {code} "}).status_code == 200


def test_wrong_code_counts_attempts_then_closes(client):
    register(client)
    code = last_code("a@example.com")
    for left in (4, 3, 2, 1):
        r = client.post("/v1/auth/verify-email", json={"code": wrong(code)})
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "invalid_code"
        assert r.json()["error"]["details"]["attempts_left"] == left
    r = client.post("/v1/auth/verify-email", json={"code": wrong(code)})
    assert r.json()["error"]["code"] == "code_expired"
    # Even the right code no longer works: a new one has to be sent.
    r = client.post("/v1/auth/verify-email", json={"code": code})
    assert r.status_code == 400 and r.json()["error"]["code"] == "code_expired"


def test_expired_code_is_rejected(client):
    register(client)
    with SessionLocal() as db:
        db.execute(update(EmailCode).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        db.commit()
    r = client.post("/v1/auth/verify-email", json={"code": last_code("a@example.com")})
    assert r.status_code == 400 and r.json()["error"]["code"] == "code_expired"


def test_resend_replaces_the_code_and_has_a_cooldown(client, mail):
    register(client)
    old = last_code("a@example.com")
    r = client.post("/v1/auth/resend-verification")
    assert r.status_code == 429 and r.json()["error"]["code"] == "resend_too_soon"
    assert int(r.headers["Retry-After"]) > 0

    with SessionLocal() as db:
        db.execute(update(EmailCode).values(created_at=datetime.now(UTC) - timedelta(minutes=2)))
        db.commit()
    r = client.post("/v1/auth/resend-verification")
    assert r.status_code == 200
    assert r.json()["sent_to"] == "a@example.com"
    new = last_code("a@example.com")
    if new != old:  # one in a million they match
        r = client.post("/v1/auth/verify-email", json={"code": old})
        assert r.status_code == 400
    assert client.post("/v1/auth/verify-email", json={"code": new}).status_code == 200
    assert client.post("/v1/auth/resend-verification").json()["error"]["code"] == "already_verified"


def test_send_failure_is_reported(client, monkeypatch):
    def boom(*a, **k):
        raise mailer.MailError("smtp down")

    monkeypatch.setattr("app.mailer.send", boom)
    r = register(client)
    assert r.status_code == 201
    assert r.json()["verification_email_sent"] is False
    with SessionLocal() as db:
        db.execute(update(EmailCode).values(created_at=datetime.now(UTC) - timedelta(minutes=2)))
        db.commit()
    r = client.post("/v1/auth/resend-verification")
    assert r.status_code == 503 and r.json()["error"]["code"] == "email_failed"


def test_unverified_email_can_be_claimed_by_the_real_owner(client):
    """A stranger signing up with your email can't lock you out: an unverified account is replaced."""
    register(client, password="strangers-password")
    squatter_id = client.get("/v1/auth/me").json()["user"]["id"]

    owner = new_client()
    r = register(owner, password="owners-password-123")
    assert r.status_code == 201
    assert r.json()["user"]["id"] != squatter_id
    assert client.get("/v1/auth/me").status_code == 401  # the squatter's session is gone
    assert owner.post("/v1/auth/verify-email", json={"code": last_code("a@example.com")}).status_code == 200
    with SessionLocal() as db:
        assert db.get(User, squatter_id) is None


def test_verified_email_cannot_be_taken(client):
    register(client)
    client.post("/v1/auth/verify-email", json={"code": last_code("a@example.com")})
    r = register(new_client(), password="another-password")
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"


def test_unverified_user_can_log_in_but_stays_locked(client):
    register(client)
    other = new_client()
    r = other.post("/v1/auth/login", json={"email": "a@example.com", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["user"]["email_verified"] is False
    assert other.get("/v1/events").status_code == 403
    assert other.post("/v1/auth/logout").status_code == 204


def test_codes_are_stored_hashed(client):
    register(client)
    code = last_code("a@example.com")
    with SessionLocal() as db:
        row = db.scalar(select(EmailCode))
        assert code not in row.code_hash and len(row.code_hash) == 64


@pytest.mark.parametrize("backend", ["console"])
def test_console_backend_logs_instead_of_sending(backend, monkeypatch, caplog):
    monkeypatch.undo()  # use the real mailer.send
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "mail_backend", backend)
    with caplog.at_level("WARNING", logger="hookflow.mail"):
        mailer.send("x@example.com", "Subject", "123456 body")
    assert "123456" in caplog.text


def test_brevo_backend_posts_to_the_api(monkeypatch):
    import httpx
    import respx

    from app.config import get_settings

    monkeypatch.undo()
    s = get_settings()
    monkeypatch.setattr(s, "mail_backend", "brevo")
    monkeypatch.setattr(s, "brevo_api_key", "xkeysib-test")
    monkeypatch.setattr(s, "mail_from_email", "me@gmail.com")
    with respx.mock:
        route = respx.post("https://api.brevo.com/v3/smtp/email").mock(return_value=httpx.Response(201))
        mailer.send("x@example.com", "Hi", "body")
        req = route.calls.last.request
        assert req.headers["api-key"] == "xkeysib-test"
        assert b'"me@gmail.com"' in req.content and b'"x@example.com"' in req.content

        respx.post("https://api.brevo.com/v3/smtp/email").mock(return_value=httpx.Response(401, text="bad key"))
        with pytest.raises(mailer.MailError):
            mailer.send("x@example.com", "Hi", "body")


def test_gmail_backend_refreshes_token_and_sends(monkeypatch):
    import base64

    import httpx
    import respx

    from app.config import get_settings

    monkeypatch.undo()
    s = get_settings()
    for k, v in {"mail_backend": "gmail", "gmail_client_id": "cid", "gmail_client_secret": "csecret",
                 "gmail_refresh_token": "rtok", "mail_from_email": "me@gmail.com"}.items():
        monkeypatch.setattr(s, k, v)
    monkeypatch.setattr(mailer, "_token", None)
    with respx.mock:
        token = respx.post(mailer.GOOGLE_TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "atok", "expires_in": 3600}))
        send = respx.post(mailer.GMAIL_SEND_URL).mock(return_value=httpx.Response(200, json={"id": "m1"}))
        mailer.send("x@example.com", "123456 is your code", "body 123456")
        mailer.send("y@example.com", "again", "body")
        assert token.call_count == 1  # the access token is reused
        assert b"refresh_token=rtok" in token.calls.last.request.content
        req = send.calls[0].request
        assert req.headers["authorization"] == "Bearer atok"
        raw = base64.urlsafe_b64decode(httpx.Response(200, content=req.content).json()["raw"])
        assert b"To: x@example.com" in raw and b"me@gmail.com" in raw and b"123456" in raw

        # A revoked access token is refreshed once and the send retried.
        respx.post(mailer.GMAIL_SEND_URL).mock(side_effect=[httpx.Response(401), httpx.Response(200, json={})])
        mailer.send("z@example.com", "s", "b")
        assert token.call_count == 2

        # A revoked refresh token is reported as a send failure.
        monkeypatch.setattr(mailer, "_token", None)
        respx.post(mailer.GOOGLE_TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
        with pytest.raises(mailer.MailError):
            mailer.send("x@example.com", "s", "b")
