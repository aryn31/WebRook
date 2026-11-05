"""Forgot password: a code is emailed, and entering it with a new password resets it."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import AuditLog, EmailCode, User
from tests.conftest import last_code, make_user

PASSWORD = "correct-horse-battery"
NEW = "a-brand-new-password"


def new_client() -> TestClient:
    from app.main import app

    return TestClient(app)


def forgot(client: TestClient, email: str = "a@example.com"):
    return client.post("/v1/auth/forgot-password", json={"email": email})


def reset(client: TestClient, code: str, email: str = "a@example.com", password: str = NEW):
    return client.post("/v1/auth/reset-password", json={"email": email, "code": code, "new_password": password})


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


def login(client: TestClient, password: str, email: str = "a@example.com"):
    return client.post("/v1/auth/login", json={"email": email, "password": password})


def test_reset_flow(client, mail):
    make_user(client)
    other = new_client()
    assert login(other, PASSWORD).status_code == 200

    anon = new_client()
    r = forgot(anon, "A@Example.com")
    assert r.status_code == 202
    assert mail[-1]["to"] == "a@example.com"
    assert mail[-1]["subject"] == "Reset your HookFlow password"
    code = last_code("a@example.com")
    assert code not in mail[-1]["subject"]
    assert "/forgot-password" in mail[-1]["text"] and code in mail[-1]["html"]

    r = reset(anon, code)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["email"] == "a@example.com"
    # This browser is logged in; every earlier session is signed out.
    assert anon.get("/v1/endpoints").status_code == 200
    assert client.get("/v1/auth/me").status_code == 401
    assert other.get("/v1/auth/me").status_code == 401
    # Only the new password works now.
    assert login(new_client(), PASSWORD).status_code == 401
    assert login(new_client(), NEW).status_code == 200
    with SessionLocal() as db:
        row = db.scalar(select(AuditLog).where(AuditLog.action == "auth.password_reset"))
        assert row is not None and row.details["signed_out_sessions"] == 2


def test_same_answer_for_unknown_email(client, mail):
    make_user(client)
    mail.clear()
    known = forgot(new_client(), "a@example.com")
    unknown = forgot(new_client(), "nobody@example.com")
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert [m["to"] for m in mail] == ["a@example.com"]
    r = reset(new_client(), "123456", email="nobody@example.com")
    assert r.status_code == 400 and r.json()["error"]["code"] == "code_expired"


def test_code_can_be_used_once(client):
    make_user(client)
    forgot(client)
    code = last_code("a@example.com")
    assert reset(new_client(), code).status_code == 200
    r = reset(new_client(), code, password="yet-another-password")
    assert r.status_code == 400 and r.json()["error"]["code"] == "code_expired"


def test_wrong_codes_count_and_close_the_code(client):
    make_user(client)
    forgot(client)
    code = last_code("a@example.com")
    r = reset(new_client(), wrong(code))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_code"
    assert r.json()["error"]["details"]["attempts_left"] == 4
    for _ in range(4):
        reset(new_client(), wrong(code))
    r = reset(new_client(), code)  # right code, but too late
    assert r.status_code == 400 and r.json()["error"]["code"] == "code_expired"
    assert login(new_client(), PASSWORD).status_code == 200


def test_expired_code(client):
    make_user(client)
    forgot(client)
    code = last_code("a@example.com")
    with SessionLocal() as db:
        db.execute(update(EmailCode).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        db.commit()
    r = reset(new_client(), code)
    assert r.status_code == 400 and r.json()["error"]["code"] == "code_expired"


def test_verification_code_does_not_reset_the_password(client):
    client.post("/v1/auth/register", json={"email": "a@example.com", "password": PASSWORD})
    code = last_code("a@example.com")  # the sign-up code
    r = reset(new_client(), code)
    assert r.status_code == 400 and r.json()["error"]["code"] == "code_expired"


def test_resend_cooldown_is_silent(client, mail):
    make_user(client)
    mail.clear()
    assert forgot(new_client()).status_code == 202
    assert forgot(new_client()).status_code == 202  # too soon: same answer, no second email
    assert len(mail) == 1


def test_new_password_must_be_long_enough(client):
    make_user(client)
    forgot(client)
    r = reset(new_client(), last_code("a@example.com"), password="short")
    assert r.status_code == 422


def test_reset_verifies_an_unverified_email(client):
    client.post("/v1/auth/register", json={"email": "a@example.com", "password": PASSWORD})
    forgot(new_client())
    r = reset(new_client(), last_code("a@example.com"))
    assert r.status_code == 200 and r.json()["user"]["email_verified"] is True
    with SessionLocal() as db:
        assert db.scalar(select(User.email_verified_at)) is not None
