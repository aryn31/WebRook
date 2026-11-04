"""The Security page: change password, see where you're logged in, sign out other sessions."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import AuditLog, UserSession
from tests.conftest import make_user

PASSWORD = "correct-horse-battery"
NEW_PASSWORD = "a-much-better-passphrase"


def login(app_client: TestClient, email: str = "a@example.com", password: str = PASSWORD, ua: str = "TestUA/1.0"):
    from app.main import app

    c = TestClient(app)
    r = c.post("/v1/auth/login", json={"email": email, "password": password}, headers={"User-Agent": ua})
    return c, r


def actions(user_email: str = "a@example.com") -> list[str]:
    with SessionLocal() as db:
        return list(db.scalars(select(AuditLog.action).order_by(AuditLog.created_at)))


def test_sessions_list_shows_devices_and_marks_current(client):
    make_user(client)
    other, r = login(client, ua="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/604.1")
    assert r.status_code == 200

    r = client.get("/v1/auth/sessions")
    assert r.status_code == 200
    rows = r.json()["data"]
    assert len(rows) == 2
    # The phone logged in most recently, so it comes first.
    assert "iPhone" in rows[0]["user_agent"]
    assert [row["current"] for row in rows] == [False, True]
    assert all(row["ip_address"] and row["last_seen_at"] for row in rows)
    assert "token_hash" not in rows[0]


def test_sessions_only_lists_your_own(client):
    make_user(client)
    from app.main import app

    stranger = TestClient(app)
    make_user(stranger, "b@example.com")
    assert len(client.get("/v1/auth/sessions").json()["data"]) == 1
    theirs = stranger.get("/v1/auth/sessions").json()["data"][0]["id"]
    # Can't sign out someone else's session.
    assert client.delete(f"/v1/auth/sessions/{theirs}").status_code == 404
    assert stranger.get("/v1/auth/me").status_code == 200


def test_sign_out_one_session(client):
    make_user(client)
    other, _ = login(client)
    rows = client.get("/v1/auth/sessions").json()["data"]
    target = next(r["id"] for r in rows if not r["current"])

    assert client.delete(f"/v1/auth/sessions/{target}").status_code == 204
    assert other.get("/v1/auth/me").status_code == 401
    assert client.get("/v1/auth/me").status_code == 200
    assert client.delete(f"/v1/auth/sessions/{target}").status_code == 404  # already signed out
    assert "auth.session_signed_out" in actions()


def test_signing_out_current_session_logs_you_out(client):
    make_user(client)
    me = client.get("/v1/auth/sessions").json()["data"][0]
    r = client.delete(f"/v1/auth/sessions/{me['id']}")
    assert r.status_code == 204
    assert "hf_session" in r.headers.get("set-cookie", "")
    assert client.get("/v1/auth/me").status_code == 401


def test_sign_out_others(client):
    make_user(client)
    a, _ = login(client)
    b, _ = login(client)
    r = client.post("/v1/auth/sessions/sign-out-others")
    assert r.status_code == 200
    assert r.json() == {"signed_out_sessions": 2}
    assert a.get("/v1/auth/me").status_code == 401
    assert b.get("/v1/auth/me").status_code == 401
    assert client.get("/v1/auth/me").status_code == 200
    assert len(client.get("/v1/auth/sessions").json()["data"]) == 1
    assert "auth.sessions_signed_out" in actions()


def test_change_password(client):
    make_user(client)
    other, _ = login(client)
    old_cookie = client.cookies.get("hf_session")

    r = client.post("/v1/auth/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert r.status_code == 200, r.text
    assert r.json() == {"signed_out_sessions": 1}

    # This browser stays logged in with a fresh token; the old token and other devices are signed out.
    assert client.cookies.get("hf_session") != old_cookie
    assert client.get("/v1/auth/me").status_code == 200
    assert other.get("/v1/auth/me").status_code == 401
    from app.main import app

    stale = TestClient(app)
    stale.cookies.set("hf_session", old_cookie)
    assert stale.get("/v1/auth/me").status_code == 401

    assert login(client, password=PASSWORD)[1].status_code == 401
    assert login(client, password=NEW_PASSWORD)[1].status_code == 200
    assert "auth.password_changed" in actions()


def test_change_password_keeps_team_account(client):
    """Changing your password while working in a team keeps you in that team."""
    make_user(client)  # owner a@
    from app.main import app

    member = TestClient(app)
    make_user(member, "m@example.com")
    inv = client.post("/v1/team/invites", json={"email": "m@example.com", "role": "developer"}).json()
    token = inv["accept_path"].rsplit("/", 1)[1]
    assert member.post(f"/v1/invites/{token}/accept").status_code == 200
    assert member.get("/v1/auth/me").json()["account"]["personal"] is False

    r = member.post("/v1/auth/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert r.status_code == 200
    me = member.get("/v1/auth/me").json()
    assert me["account"]["personal"] is False
    # Recorded in the member's own audit log, not the team's.
    with SessionLocal() as db:
        row = db.scalar(select(AuditLog).where(AuditLog.action == "auth.password_changed"))
        assert row.user_id == me["user"]["id"]


def test_change_password_rejections(client):
    make_user(client)
    r = client.post("/v1/auth/password", json={"current_password": "wrong-password", "new_password": NEW_PASSWORD})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_current_password"

    r = client.post("/v1/auth/password", json={"current_password": PASSWORD, "new_password": PASSWORD})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "same_password"

    r = client.post("/v1/auth/password", json={"current_password": PASSWORD, "new_password": "short"})
    assert r.status_code == 422

    # Nothing changed.
    assert login(client)[1].status_code == 200


def test_security_routes_need_a_dashboard_session(client):
    make_user(client)
    key = client.post("/v1/api-keys", json={"name": "k"}).json()["key"]
    from app.main import app

    api = TestClient(app)
    h = {"Authorization": f"Bearer {key}"}
    assert api.get("/v1/auth/sessions", headers=h).status_code == 403
    assert api.post("/v1/auth/sessions/sign-out-others", headers=h).status_code == 403
    body = {"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    assert api.post("/v1/auth/password", json=body, headers=h).status_code == 403
    assert TestClient(app).get("/v1/auth/sessions").status_code == 401


def test_expired_sessions_are_not_listed(client):
    make_user(client)
    login(client)
    with SessionLocal() as db:
        db.execute(
            update(UserSession)
            .where(UserSession.created_at == db.scalar(select(UserSession.created_at).order_by(UserSession.created_at.desc()).limit(1)))
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        db.commit()
    assert len(client.get("/v1/auth/sessions").json()["data"]) == 1


def test_last_seen_is_updated_but_not_every_request(client):
    make_user(client)
    with SessionLocal() as db:
        db.execute(update(UserSession).values(last_seen_at=datetime.now(UTC) - timedelta(hours=1), ip_address=None))
        db.commit()
    client.get("/v1/auth/me")
    with SessionLocal() as db:
        s = db.scalar(select(UserSession))
        first = s.last_seen_at
        assert datetime.now(UTC) - first < timedelta(minutes=1)
        assert s.ip_address
    client.get("/v1/auth/me")
    with SessionLocal() as db:
        assert db.scalar(select(UserSession)).last_seen_at == first
