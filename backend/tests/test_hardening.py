"""Milestone 3: SSRF pinning, DNS and database failures, ingestion limits, per-endpoint concurrency, retention,
metrics, alerts and client IPs."""

import ipaddress
import logging
import socket
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
import respx
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from starlette.requests import Request

from app import ops, urlguard
from app.clientip import client_ip
from app.config import get_settings
from app.db import SessionLocal
from app.models import AuditLog, Delivery, DeliveryAttempt, Event, OutboxMessage, User
from app.worker import concurrency
from app.worker.engine import delete_expired, process_delivery, send

URL = "https://hooks.example.com/in"


@pytest.fixture
def setup(user_a):
    c, h = user_a
    ep = c.post("/v1/endpoints", json={"url": URL, "event_types": ["order.created"]}, headers=h).json()
    evt = c.post("/v1/events", json={"event_type": "order.created", "data": {"n": 1}}, headers=h).json()
    dlv = c.get(f"/v1/events/{evt['event_id']}/deliveries", headers=h).json()["data"][0]["id"]
    return c, h, dlv, ep["id"]


def _delivery(delivery_id: str) -> Delivery:
    with SessionLocal() as db:
        return db.get(Delivery, delivery_id)


def _set_user(**values) -> None:
    with SessionLocal() as db:
        db.execute(update(User).values(**values))
        db.commit()


def _post_event(c, h, n=1, **headers):
    return c.post("/v1/events", json={"event_type": "order.created", "data": {"n": n}}, headers={**h, **headers})


# --- SSRF: DNS pinning ------------------------------------------------------------------------------------


@pytest.fixture
def local_server():
    """A real HTTP server on 127.0.0.1. Returns its port."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", 0)))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()


@pytest.fixture
def blocking(monkeypatch):
    monkeypatch.setattr(get_settings(), "block_private_destinations", True)


def test_connection_goes_to_the_address_that_was_checked(monkeypatch, blocking, local_server):
    """DNS rebinding: the first lookup is safe, any later one would be internal. Only one lookup may happen,
    and the connection must use its answer."""
    # Treat 127.0.0.1 as public for this test so the local server stands in for a real destination.
    real_check = urlguard._is_blocked_ip
    monkeypatch.setattr(urlguard, "_is_blocked_ip",
                        lambda ip: False if ip == ipaddress.ip_address("127.0.0.1") else real_check(ip))
    lookups = []

    def rebinding_dns(host, port, *args, **kwargs):
        try:  # an IP literal resolves to itself, as with real DNS
            ipaddress.ip_address(host)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, port))]
        except ValueError:
            pass
        lookups.append(host)
        ip = "127.0.0.1" if len(lookups) == 1 else "10.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    monkeypatch.setattr(socket, "getaddrinfo", rebinding_dns)
    outcome = send(f"http://rebind.example.com:{local_server}/hook", b"{}", {})
    assert outcome.success and outcome.status_code == 200
    assert lookups == ["rebind.example.com"]


def test_host_resolving_to_private_address_is_refused_without_connecting(monkeypatch, blocking):
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda host, port, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", port))])
    connected = []
    monkeypatch.setattr(urlguard.httpcore.SyncBackend, "connect_tcp",
                        lambda self, *a, **k: connected.append(a))
    outcome = send("https://sneaky.example.com/hook", b"{}", {})
    assert not outcome.success and not outcome.retryable
    assert "private or reserved" in outcome.error
    assert connected == []


def test_one_private_address_among_public_ones_is_refused(monkeypatch, blocking):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port)),
    ])
    with pytest.raises(urlguard.UnsafeDestination):
        urlguard.resolve_public("mixed.example.com", 443)


def test_dns_failure_is_retried(setup, monkeypatch, blocking):
    _, _, dlv, _ = setup

    def no_dns(*args, **kwargs):
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", no_dns)
    assert process_delivery(dlv) == "failed"
    d = _delivery(dlv)
    assert d.status == "retrying" and d.next_attempt_at > datetime.now(UTC)
    assert d.last_error == "Could not resolve host 'hooks.example.com'."


# --- Database unavailable ---------------------------------------------------------------------------------


def _db_down(*args, **kwargs):
    raise OperationalError("SELECT 1", {}, Exception("connection refused"))


def test_ingestion_returns_503_when_database_is_down(user_a, monkeypatch):
    c, h = user_a
    monkeypatch.setattr("app.routers.events._ingest", _db_down)
    r = _post_event(c, h)
    assert r.status_code == 503 and r.headers["Retry-After"] == "5"
    assert r.json()["error"]["code"] == "service_unavailable"
    # The failed request didn't use up quota.
    monkeypatch.undo()
    assert _post_event(c, h).headers["X-Quota-Remaining"] == str(get_settings().daily_event_quota - 1)


def test_readiness_fails_when_database_is_down(client, monkeypatch):
    monkeypatch.setattr("app.routers.health.engine.connect", _db_down)
    r = client.get("/health/ready")
    assert r.status_code == 503 and r.json()["checks"]["database"] == "unavailable"


def test_worker_recovers_after_database_outage(setup, monkeypatch):
    _, _, dlv, _ = setup
    monkeypatch.setattr("app.worker.engine.SessionLocal", _db_down)
    with pytest.raises(OperationalError):
        process_delivery(dlv)  # the task fails; Celery drops the message
    monkeypatch.undo()
    assert _delivery(dlv).status == "pending"  # nothing was lost or half-recorded

    with respx.mock:
        respx.post(URL).mock(return_value=httpx.Response(200))
        assert process_delivery(dlv) == "delivered"


def test_outbox_publish_never_raises_when_database_is_down(monkeypatch):
    from app import outbox

    monkeypatch.setattr("app.outbox.SessionLocal", _db_down)
    assert outbox.publish_ids(["obx_1"]) == 0


# --- Ingestion rate limit and quota -----------------------------------------------------------------------


def test_successful_ingestion_reports_limits(user_a):
    c, h = user_a
    r = _post_event(c, h)
    assert r.status_code == 202
    s = get_settings()
    assert r.headers["X-RateLimit-Limit"] == str(s.event_rate_limit_per_minute)
    assert r.headers["X-RateLimit-Remaining"] == str(s.event_rate_limit_per_minute - 1)
    assert r.headers["X-Quota-Limit"] == str(s.daily_event_quota)
    assert 0 < int(r.headers["X-Quota-Reset"]) <= 86400


def test_per_account_rate_limit(user_a, user_b):
    c, h = user_a
    _set_user(event_rate_limit_per_minute=2)
    assert _post_event(c, h).status_code == 202
    assert _post_event(c, h).status_code == 202
    r = _post_event(c, h)
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert int(r.headers["Retry-After"]) > 0 and r.headers["X-RateLimit-Remaining"] == "0"


def test_daily_quota_and_idempotent_retries_dont_count(user_a):
    c, h = user_a
    _set_user(daily_event_quota=2)
    assert _post_event(c, h, 1, **{"Idempotency-Key": "k1"}).headers["X-Quota-Remaining"] == "1"
    retry = _post_event(c, h, 1, **{"Idempotency-Key": "k1"})
    assert retry.headers["Idempotent-Replayed"] == "true" and retry.headers["X-Quota-Remaining"] == "1"
    assert _post_event(c, h, 2).headers["X-Quota-Remaining"] == "0"
    r = _post_event(c, h, 3)
    assert r.status_code == 429 and r.json()["error"]["code"] == "quota_exceeded"
    assert r.headers["X-Quota-Remaining"] == "0" and int(r.headers["Retry-After"]) > 0


def test_zero_means_unlimited(user_a):
    c, h = user_a
    _set_user(event_rate_limit_per_minute=0, daily_event_quota=0)
    r = _post_event(c, h)
    assert r.status_code == 202 and "X-RateLimit-Limit" not in r.headers and "X-Quota-Limit" not in r.headers


def test_limits_fail_open_without_redis(user_a, monkeypatch):
    import redis

    c, h = user_a

    def redis_down(*args, **kwargs):
        raise redis.ConnectionError("down")

    monkeypatch.setattr("app.ratelimit.get_redis", lambda: type("R", (), {"pipeline": redis_down})())
    assert _post_event(c, h).status_code == 202


# --- Per-endpoint concurrency -----------------------------------------------------------------------------


@respx.mock
def test_busy_endpoint_defers_delivery_without_using_an_attempt(setup, monkeypatch):
    _, _, dlv, endpoint_id = setup
    monkeypatch.setattr(get_settings(), "endpoint_max_concurrency", 1)
    respx.post(URL).mock(return_value=httpx.Response(200))
    assert concurrency.acquire(endpoint_id, "dlv_other", 1, 60)  # another delivery is in flight

    assert process_delivery(dlv) == "deferred"
    d = _delivery(dlv)
    assert d.status == "pending" and d.attempt_count == 0 and d.next_attempt_at > datetime.now(UTC)
    with SessionLocal() as db:
        staged = db.scalars(select(OutboxMessage).where(OutboxMessage.delivery_id == dlv,
                                                         OutboxMessage.published_at.is_(None))).all()
    assert any(m.available_at > datetime.now(UTC) for m in staged)

    concurrency.release(endpoint_id, "dlv_other")
    with SessionLocal() as db:
        db.execute(update(Delivery).where(Delivery.id == dlv).values(next_attempt_at=datetime.now(UTC)))
        db.commit()
    assert process_delivery(dlv) == "delivered"
    assert concurrency.in_flight(endpoint_id) == 0  # the slot was given back


def test_concurrency_slots_expire():
    assert concurrency.acquire("ep_x", "dlv_1", 1, 0)  # expires immediately
    assert concurrency.acquire("ep_x", "dlv_2", 1, 60)


# --- Retention --------------------------------------------------------------------------------------------


def test_old_finished_events_are_deleted_with_their_history(setup):
    c, h, dlv, _ = setup
    keep = _post_event(c, h, 2).json()["event_id"]  # recent: kept
    long_ago = datetime.now(UTC) - timedelta(days=get_settings().event_retention_days + 1)
    with SessionLocal() as db:
        old_event = db.get(Delivery, dlv).event_id
        db.execute(update(Event).where(Event.id == old_event).values(created_at=long_ago))
        db.execute(update(Delivery).where(Delivery.id == dlv).values(status="delivered"))
        db.add(DeliveryAttempt(delivery_id=dlv, attempt_number=1, started_at=long_ago, success=True))
        db.execute(update(AuditLog).values(created_at=datetime.now(UTC) - timedelta(days=400)))
        db.commit()

    assert delete_expired(datetime.now(UTC)) >= 2
    with SessionLocal() as db:
        assert db.get(Event, old_event) is None and db.get(Delivery, dlv) is None
        assert db.scalars(select(DeliveryAttempt).where(DeliveryAttempt.delivery_id == dlv)).all() == []
        assert db.get(Event, keep) is not None
        assert db.scalars(select(AuditLog)).all() == []


def test_old_event_with_delivery_in_progress_is_kept(setup):
    _, _, dlv, _ = setup
    with SessionLocal() as db:
        event_id = db.get(Delivery, dlv).event_id
        db.execute(update(Event).values(created_at=datetime.now(UTC) - timedelta(days=90)))
        db.commit()
    delete_expired(datetime.now(UTC))
    with SessionLocal() as db:
        assert db.get(Event, event_id) is not None


def test_retention_zero_keeps_everything(setup, monkeypatch):
    _, _, dlv, _ = setup
    monkeypatch.setattr(get_settings(), "event_retention_days", 0)
    with SessionLocal() as db:
        db.execute(update(Event).values(created_at=datetime.now(UTC) - timedelta(days=900)))
        db.execute(update(Delivery).values(status="delivered"))
        db.commit()
    delete_expired(datetime.now(UTC))
    assert _delivery(dlv) is not None


# --- Metrics and alerts -----------------------------------------------------------------------------------


def test_metrics_report_requests_and_queue(setup):
    c, h, _, _ = setup
    ops.beat_heartbeat()
    text = c.get("/metrics").text
    assert 'hookflow_deliveries_queued{status="pending"} 1.0' in text
    assert 'route="/v1/events"' in text and 'route="/v1/events/{event_id}/deliveries"' in text
    assert "hookflow_http_request_duration_seconds_bucket" in text
    assert "hookflow_pipeline_metrics_up 1.0" in text
    assert "hookflow_worker_last_seen_seconds" in text


def test_metrics_token(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "metrics_token", "s3cret")
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_metrics_survive_database_outage(client, monkeypatch):
    monkeypatch.setattr("app.metrics.SessionLocal", _db_down)
    r = client.get("/metrics")
    assert r.status_code == 200 and "hookflow_pipeline_metrics_up 0.0" in r.text


def test_stuck_queue_alerts_once_then_resolves(setup, caplog):
    _, _, dlv, _ = setup
    with SessionLocal() as db:
        db.execute(update(Delivery).values(next_attempt_at=datetime.now(UTC) - timedelta(minutes=10)))
        db.commit()
    caplog.set_level(logging.INFO, logger="hookflow.monitor")
    with SessionLocal() as db:
        assert "delivery_queue_delayed" in ops.check_alerts(ops.snapshot(db))
        assert "delivery_queue_delayed" in ops.check_alerts(ops.snapshot(db))
    alerts = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(alerts) == 1 and "ALERT delivery_queue_delayed" in alerts[0].getMessage()

    with SessionLocal() as db:
        db.execute(update(Delivery).values(status="delivered"))
        db.commit()
        assert ops.check_alerts(ops.snapshot(db)) == []
    assert any("resolved" in r.getMessage() for r in caplog.records)


def test_health_reports_worker_status(client):
    assert client.get("/health/ready").json()["worker"] == "unknown"
    ops.beat_heartbeat()
    assert client.get("/health/ready").json()["worker"] == "ok"


# --- Client IP behind proxies -----------------------------------------------------------------------------


def _request(xff: str | None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "headers": headers, "client": ("10.0.0.9", 1234)})


@pytest.mark.parametrize(
    ("hops", "xff", "expected"),
    [
        (0, "203.0.113.5", "10.0.0.9"),  # no trusted proxies: header ignored
        (1, "203.0.113.5", "203.0.113.5"),
        (1, "6.6.6.6, 203.0.113.5", "203.0.113.5"),  # the client's own (forgeable) entry is skipped
        (2, "6.6.6.6, 203.0.113.5, 198.51.100.7", "203.0.113.5"),
        (2, "203.0.113.5", "203.0.113.5"),
        (1, None, "10.0.0.9"),
    ],
)
def test_client_ip(monkeypatch, hops, xff, expected):
    monkeypatch.setattr(get_settings(), "trusted_proxy_count", hops)
    assert client_ip(_request(xff)) == expected


def test_audit_log_uses_forwarded_ip(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "trusted_proxy_count", 1)
    r = client.post("/v1/auth/register", json={"email": "ip@example.com", "password": "correct-horse-battery"},
                    headers={"X-Forwarded-For": "203.0.113.5"})
    assert r.status_code == 201
    entry = client.get("/v1/audit-logs").json()["data"][0]
    assert entry["ip_address"] == "203.0.113.5"


# --- Attempt counts after replays -------------------------------------------------------------------------


def test_delivery_reports_attempts_since_last_replay(setup):
    c, h, dlv, _ = setup
    with SessionLocal() as db:
        db.execute(update(Delivery).where(Delivery.id == dlv)
                   .values(attempt_count=7, retry_base_attempt=5, max_attempts=10))
        db.commit()
    d = c.get(f"/v1/deliveries/{dlv}", headers=h).json()
    assert (d["attempt_count"], d["max_attempts"]) == (7, 10)
    assert (d["run_attempt_count"], d["run_max_attempts"]) == (2, 5)
