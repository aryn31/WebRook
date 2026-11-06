"""Email alerts when an endpoint keeps failing, and when it recovers."""

import httpx
import respx
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import AuditLog, Endpoint
from app.worker.engine import process_delivery

URL = "https://hooks.example.com/in"


def _endpoint(c, h, **extra) -> dict:
    # One attempt per delivery, so each event is exactly one attempt.
    body = {"url": URL, "event_types": ["*"], "description": "Billing", "max_attempts": 1} | extra
    return c.post("/v1/endpoints", json=body, headers=h).json()


def _fire(c, h, n: int = 1) -> None:
    for i in range(n):
        evt = c.post("/v1/events", json={"event_type": "order.created", "data": {"i": i}}, headers=h).json()
        for d in c.get(f"/v1/events/{evt['event_id']}/deliveries", headers=h).json()["data"]:
            process_delivery(d["id"])


def _alerts(mail) -> list[dict]:
    return [m for m in mail if m["subject"].startswith(("Alert:", "Resolved:"))]


def _ep(ep_id: str) -> Endpoint:
    with SessionLocal() as db:
        return db.get(Endpoint, ep_id)


@respx.mock
def test_alert_after_threshold_then_one_recovery(user_a, mail):
    c, h = user_a
    ep = _endpoint(c, h)
    route = respx.post(URL).mock(return_value=httpx.Response(503))

    _fire(c, h, 4)
    assert _alerts(mail) == []
    assert _ep(ep["id"]).consecutive_failures == 4

    _fire(c, h, 1)  # 5th failure in a row
    [alert] = _alerts(mail)
    assert alert["to"] == "a@example.com"
    assert alert["subject"] == "Alert: Billing is failing"
    assert "HTTP 503" in alert["text"] and f"/endpoints/{ep['id']}" in alert["text"]
    assert "/security" in alert["text"]  # how to turn them off
    assert c.get(f"/v1/endpoints/{ep['id']}", headers=h).json()["alert_sent_at"] is not None

    _fire(c, h, 6)  # still down: no more emails
    assert len(_alerts(mail)) == 1

    route.mock(return_value=httpx.Response(200))
    _fire(c, h, 1)
    alerts = _alerts(mail)
    assert len(alerts) == 2
    assert alerts[1]["subject"] == "Resolved: Billing is working again"
    assert "11 deliveries ran out of attempts" in alerts[1]["text"]
    e = _ep(ep["id"])
    assert e.consecutive_failures == 0 and e.failing_since is None and e.alert_sent_at is None

    _fire(c, h, 2)  # healthy: nothing more
    assert len(_alerts(mail)) == 2


@respx.mock
def test_a_success_resets_the_count_before_any_alert(user_a, mail):
    c, h = user_a
    _endpoint(c, h)
    route = respx.post(URL)
    route.mock(return_value=httpx.Response(500))
    _fire(c, h, 4)
    route.mock(return_value=httpx.Response(200))
    _fire(c, h, 1)
    route.mock(return_value=httpx.Response(500))
    _fire(c, h, 4)
    assert _alerts(mail) == []  # never 5 in a row; and no "resolved" email without an alert first


@respx.mock
def test_retries_count_as_failures(user_a, mail, monkeypatch):
    monkeypatch.setattr(get_settings(), "alert_after_failures", 2)
    c, h = user_a
    ep = _endpoint(c, h, max_attempts=3, retry_schedule=[1])
    respx.post(URL).mock(return_value=httpx.Response(503))
    evt = c.post("/v1/events", json={"event_type": "x", "data": {}}, headers=h).json()
    dlv = c.get(f"/v1/events/{evt['event_id']}/deliveries", headers=h).json()["data"][0]["id"]
    process_delivery(dlv)
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from app.models import Delivery
    with SessionLocal() as db:
        db.execute(update(Delivery).where(Delivery.id == dlv).values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1)))
        db.commit()
    process_delivery(dlv)  # the retry: 2nd failed attempt
    assert len(_alerts(mail)) == 1
    assert _ep(ep["id"]).consecutive_failures == 2


@respx.mock
def test_turned_off_means_no_email(user_a, mail):
    c, h = user_a
    r = c.patch("/v1/auth/preferences", json={"failure_alerts": False})
    assert r.status_code == 200 and r.json()["user"]["failure_alerts"] is False
    assert c.get("/v1/auth/me").json()["user"]["failure_alerts"] is False
    with SessionLocal() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "auth.preferences_changed")) is not None

    ep = _endpoint(c, h)
    respx.post(URL).mock(return_value=httpx.Response(503))
    _fire(c, h, 5)
    assert _alerts(mail) == []
    assert _ep(ep["id"]).alert_sent_at is not None  # the alert happened, there was just nobody to tell


def test_preferences_need_a_dashboard_session(user_a):
    c, h = user_a
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as anon:
        assert anon.patch("/v1/auth/preferences", json={"failure_alerts": False}, headers=h).status_code in (401, 403)


@respx.mock
def test_admins_get_alerts_developers_dont(user_a, mail):
    from tests.conftest import make_user
    from fastapi.testclient import TestClient

    from app.main import app
    owner, h = user_a
    for email, role in [("admin@example.com", "admin"), ("dev@example.com", "developer")]:
        token = owner.post("/v1/team/invites", json={"email": email, "role": role}).json()["token"]
        with TestClient(app) as other:
            make_user(other, email)
            assert other.post(f"/v1/invites/{token}/accept").status_code == 200

    _endpoint(owner, h)
    respx.post(URL).mock(return_value=httpx.Response(503))
    _fire(owner, h, 5)
    assert sorted(m["to"] for m in _alerts(mail)) == ["a@example.com", "admin@example.com"]


@respx.mock
def test_mail_failure_lets_the_next_failure_retry(user_a, mail, monkeypatch):
    from app import mailer
    c, h = user_a
    ep = _endpoint(c, h)
    respx.post(URL).mock(return_value=httpx.Response(503))

    def broken(*a, **k):
        raise mailer.MailError("smtp down")
    monkeypatch.setattr("app.mailer.send", broken)
    _fire(c, h, 5)
    assert _ep(ep["id"]).alert_sent_at is None  # nobody got it, so it isn't marked sent

    monkeypatch.setattr("app.mailer.send", lambda to, subject, text, html=None: mail.append(
        {"to": to, "subject": subject, "text": text, "html": html}))
    _fire(c, h, 1)
    assert len(_alerts(mail)) == 1


def test_threshold_zero_turns_alerts_off(user_a, mail, monkeypatch):
    monkeypatch.setattr(get_settings(), "alert_after_failures", 0)
    c, h = user_a
    _endpoint(c, h)
    with respx.mock:
        respx.post(URL).mock(return_value=httpx.Response(503))
        _fire(c, h, 6)
    assert _alerts(mail) == []
