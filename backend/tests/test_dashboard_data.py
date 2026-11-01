"""Data behind the dashboard: usage, endpoint health and latency stats."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.db import SessionLocal
from app.models import Delivery, DeliveryAttempt, User

URL = "https://hooks.example.com/in"


def _endpoint(c, h, url=URL):
    return c.post("/v1/endpoints", json={"url": url, "event_types": ["order.created"]}, headers=h).json()["id"]


def _send(c, h, n=1):
    return c.post("/v1/events", json={"event_type": "order.created", "data": {"n": n}}, headers=h)


def _attempt(endpoint_id: str, success: bool, minutes_ago: int, status: int | None = None, error: str | None = None,
             duration_ms: int = 100) -> None:
    with SessionLocal() as db:
        delivery = db.query(Delivery).filter(Delivery.endpoint_id == endpoint_id).first()
        at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
        db.add(DeliveryAttempt(delivery_id=delivery.id, attempt_number=1, started_at=at, completed_at=at,
                               duration_ms=duration_ms, response_status=status, error=error, success=success))
        db.commit()


def test_usage_reports_quota_and_rate_without_counting(user_a):
    c, h = user_a
    _send(c, h, 1)
    _send(c, h, 2)
    u = c.get("/v1/usage", headers=h).json()
    assert u["events_today"] == {**u["events_today"], "used": 2, "limit": 10000, "remaining": 9998}
    assert u["requests_this_minute"]["used"] == 2 and u["requests_this_minute"]["limit"] == 600
    assert 0 < u["events_today"]["resets_in_seconds"] <= 86400
    # Reading usage doesn't use up the limit.
    assert c.get("/v1/usage", headers=h).json()["requests_this_minute"]["used"] == 2


def test_usage_shows_unlimited_and_counts_from_database(user_a, monkeypatch):
    c, h = user_a
    _send(c, h)
    with SessionLocal() as db:
        db.execute(update(User).values(daily_event_quota=0))
        db.commit()
    _send(c, h)  # not counted by the quota counter while unlimited, but still shown
    u = c.get("/v1/usage", headers=h).json()["events_today"]
    assert u["limit"] is None and u["remaining"] is None and u["used"] == 2


def test_endpoint_health_states(user_a):
    c, h = user_a
    idle = _endpoint(c, h, "https://idle.example.com/in")
    good = _endpoint(c, h, "https://good.example.com/in")
    bad = _endpoint(c, h, "https://bad.example.com/in")
    c.patch(f"/v1/endpoints/{idle}", json={"event_types": ["other.type"]}, headers=h)
    _send(c, h)
    for i in range(20):
        _attempt(good, True, minutes_ago=30 + i, status=200)
    _attempt(bad, True, minutes_ago=60, status=200)
    _attempt(bad, False, minutes_ago=20, status=500, error="Destination returned HTTP 500.")
    _attempt(bad, False, minutes_ago=10, error="Could not connect to the destination.")
    _attempt(bad, True, minutes_ago=60 * 30)  # older than 24h: ignored

    health = {e["id"]: e["health"] for e in c.get("/v1/endpoints", headers=h).json()["data"]}
    assert health[idle]["state"] == "idle" and health[idle]["success_rate"] is None
    assert health[good] | {"last_attempt_at": None} == {
        "state": "healthy", "attempts": 20, "successes": 20, "success_rate": 1.0, "last_attempt_at": None,
        "last_success": True, "last_status_code": 200, "last_error": None,
    }
    assert health[bad]["state"] == "failing" and health[bad]["attempts"] == 3
    assert health[bad]["last_error"] == "Could not connect to the destination."

    detail = c.get(f"/v1/endpoints/{bad}", headers=h).json()
    assert detail["health"]["state"] == "failing"


def test_endpoint_degraded_when_last_attempt_succeeded(user_a):
    c, h = user_a
    ep = _endpoint(c, h)
    _send(c, h)
    _attempt(ep, False, minutes_ago=20, status=503)
    _attempt(ep, True, minutes_ago=5, status=200)
    assert c.get(f"/v1/endpoints/{ep}", headers=h).json()["health"]["state"] == "degraded"


def test_endpoint_health_is_tenant_scoped(user_a, user_b):
    c, h = user_a
    ep = _endpoint(c, h)
    _send(c, h)
    _attempt(ep, True, minutes_ago=5)
    cb, hb = user_b
    assert cb.get(f"/v1/endpoints/{ep}", headers=hb).status_code == 404


def test_stats_latency(user_a):
    c, h = user_a
    assert c.get("/v1/stats?range=24h", headers=h).json()["latency_ms"] is None
    ep = _endpoint(c, h)
    _send(c, h)
    for ms in (100, 200, 300, 400, 1000):
        _attempt(ep, True, minutes_ago=5, duration_ms=ms)
    lat = c.get("/v1/stats?range=24h", headers=h).json()["latency_ms"]
    assert lat["p50"] == 300 and 400 < lat["p95"] <= 1000
