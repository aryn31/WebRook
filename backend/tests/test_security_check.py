"""Receiver security check: does the endpoint really verify signatures?"""

import time

import httpx
import respx
from sqlalchemy import select

from app import signing
from app.db import SessionLocal
from app.models import AuditLog

URL = "https://hooks.example.com/in"


def _endpoint(c, h) -> dict:
    return c.post("/v1/endpoints", json={"url": URL, "event_types": ["*"]}, headers=h).json()


def receiver(secret: str, *, check_signature=True, check_time=True, server_error=False):
    """A fake receiver with the given habits."""
    def handle(request: httpx.Request) -> httpx.Response:
        if check_signature:
            ts = request.headers.get("HookFlow-Timestamp", "0")
            sig = request.headers.get("HookFlow-Signature")
            if not sig or not signing.verify(secret, int(ts), request.content, sig):
                return httpx.Response(500 if server_error else 401)
            if check_time and abs(time.time() - int(ts)) > 300:
                return httpx.Response(400)
        return httpx.Response(204)
    return handle


def _check(c, h, ep_id):
    return c.post(f"/v1/endpoints/{ep_id}/security-check", headers=h)


@respx.mock
def test_pass(user_a):
    c, h = user_a
    ep = _endpoint(c, h)
    route = respx.post(URL).mock(side_effect=receiver(ep["signing_secret"]))
    r = _check(c, h, ep["id"])
    assert r.status_code == 200, r.text
    sc = r.json()["security_check"]
    assert sc["verdict"] == "pass"
    assert [p["name"] for p in sc["probes"]] == ["valid", "wrong_signature", "tampered_body", "old_timestamp",
                                                "missing_signature"]
    assert all(p["ok"] for p in sc["probes"])
    assert route.call_count == 5
    # Every test request says what it is.
    probes = {call.request.headers["HookFlow-Security-Check"] for call in route.calls}
    assert probes == {"valid", "wrong_signature", "tampered_body", "old_timestamp", "missing_signature"}
    assert all(call.request.headers["HookFlow-Event-Type"] == "hookflow.security_check" for call in route.calls)
    # Saved: shows up on the endpoint afterwards.
    assert c.get(f"/v1/endpoints/{ep['id']}", headers=h).json()["security_check"]["verdict"] == "pass"
    with SessionLocal() as db:
        row = db.scalar(select(AuditLog).where(AuditLog.action == "endpoint.security_checked"))
        assert row.details == {"verdict": "pass"}


@respx.mock
def test_fail_when_signatures_are_ignored(user_a):
    c, h = user_a
    ep = _endpoint(c, h)
    respx.post(URL).mock(return_value=httpx.Response(200))
    sc = _check(c, h, ep["id"]).json()["security_check"]
    assert sc["verdict"] == "fail"
    assert "fake events" in sc["summary"]
    bad = [p["name"] for p in sc["probes"] if not p["ok"]]
    assert bad == ["wrong_signature", "tampered_body", "old_timestamp", "missing_signature"]


@respx.mock
def test_partial_when_timestamp_is_not_checked(user_a):
    c, h = user_a
    ep = _endpoint(c, h)
    respx.post(URL).mock(side_effect=receiver(ep["signing_secret"], check_time=False))
    sc = _check(c, h, ep["id"]).json()["security_check"]
    assert sc["verdict"] == "partial"
    assert [p["name"] for p in sc["probes"] if not p["ok"]] == ["old_timestamp"]


@respx.mock
def test_inconclusive_when_valid_request_is_rejected(user_a):
    c, h = user_a
    ep = _endpoint(c, h)
    respx.post(URL).mock(return_value=httpx.Response(503))
    sc = _check(c, h, ep["id"]).json()["security_check"]
    assert sc["verdict"] == "inconclusive"


@respx.mock
def test_server_errors_are_flagged(user_a):
    c, h = user_a
    ep = _endpoint(c, h)
    respx.post(URL).mock(side_effect=receiver(ep["signing_secret"], server_error=True))
    sc = _check(c, h, ep["id"]).json()["security_check"]
    assert sc["verdict"] == "pass"  # rejected, which is what matters
    wrong = next(p for p in sc["probes"] if p["name"] == "wrong_signature")
    assert wrong["status_code"] == 500 and wrong["server_error"] is True


@respx.mock
def test_changing_the_url_clears_the_result(user_a):
    c, h = user_a
    ep = _endpoint(c, h)
    respx.post(URL).mock(side_effect=receiver(ep["signing_secret"]))
    _check(c, h, ep["id"])
    c.patch(f"/v1/endpoints/{ep['id']}", json={"url": "https://other.example.com/in"}, headers=h)
    assert c.get(f"/v1/endpoints/{ep['id']}", headers=h).json()["security_check"] is None


@respx.mock
def test_during_rotation_both_secrets_sign(user_a):
    c, h = user_a
    ep = _endpoint(c, h)
    old = ep["signing_secret"]
    c.post(f"/v1/endpoints/{ep['id']}/rotate-secret", json={"grace_period_seconds": 3600}, headers=h)
    respx.post(URL).mock(side_effect=receiver(old))  # receiver hasn't switched yet
    assert _check(c, h, ep["id"]).json()["security_check"]["verdict"] == "pass"


def test_needs_write_access_and_ownership(user_a, user_b):
    c, h = user_a
    ep = _endpoint(c, h)
    cb, hb = user_b
    assert cb.post(f"/v1/endpoints/{ep['id']}/security-check", headers=hb).status_code == 404
    read_key = c.post("/v1/api-keys", json={"name": "ro", "scopes": ["endpoints:read"]}).json()["key"]
    r = c.post(f"/v1/endpoints/{ep['id']}/security-check", headers={"Authorization": f"Bearer {read_key}"})
    assert r.status_code == 403


@respx.mock
def test_rate_limited(user_a):
    c, h = user_a
    ep = _endpoint(c, h)
    respx.post(URL).mock(return_value=httpx.Response(200))
    for _ in range(6):
        assert _check(c, h, ep["id"]).status_code == 200
    assert _check(c, h, ep["id"]).status_code == 429
