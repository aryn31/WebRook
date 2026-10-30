"""Milestone 2: idempotency, outbox, replay, per-endpoint retries, secret rotation, audit log."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import func, select, update

from app import outbox, signing
from app.config import get_settings
from app.db import SessionLocal
from app.models import AuditLog, Delivery, DeliveryAttempt, Endpoint, Event, IdempotencyKey, OutboxMessage
from app.routers.events import _ingest
from app.schemas import EventIn
from app.worker.engine import process_delivery

URL = "https://hooks.example.com/in"
EP = {"url": URL, "event_types": ["order.created"]}
EVENT = {"event_type": "order.created", "data": {"order_id": "ORD-101", "amount": 2499}}


def _delivery(delivery_id: str) -> Delivery:
    with SessionLocal() as db:
        return db.get(Delivery, delivery_id)


def _make_due(delivery_id: str) -> None:
    with SessionLocal() as db:
        db.execute(update(Delivery).where(Delivery.id == delivery_id)
                   .values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1)))
        db.commit()


def _count(model) -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model))


def _send(c, h, event=EVENT, key: str | None = None):
    headers = {**h, "Idempotency-Key": key} if key else h
    return c.post("/v1/events", json=event, headers=headers)


def _deliveries(c, h, event_id: str) -> list[dict]:
    return c.get(f"/v1/events/{event_id}/deliveries", headers=h).json()["data"]


@pytest.fixture
def failed(user_a):
    """A delivery that failed permanently (HTTP 400) on its first attempt."""
    c, h = user_a
    ep = c.post("/v1/endpoints", json=EP, headers=h).json()
    evt = _send(c, h).json()
    dlv = _deliveries(c, h, evt["event_id"])[0]["id"]
    with respx.mock:
        respx.post(URL).mock(return_value=httpx.Response(400))
        process_delivery(dlv)
    assert _delivery(dlv).status == "failed"
    return c, h, dlv, evt["event_id"], ep


# --- Idempotency -------------------------------------------------------------

def test_same_idempotency_key_returns_the_original_event(user_a, queued):
    c, h = user_a
    c.post("/v1/endpoints", json=EP, headers=h)
    first = _send(c, h, key="order-101-created")
    second = _send(c, h, key="order-101-created")

    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert "Idempotent-Replayed" not in first.headers
    assert second.headers["Idempotent-Replayed"] == "true"
    assert _count(Event) == 1 and _count(Delivery) == 1
    assert len(queued) == 1  # the duplicate request doesn't queue anything
    assert c.get(f"/v1/events/{first.json()['event_id']}", headers=h).json()["idempotency_key"] == "order-101-created"


def test_equivalent_body_with_different_key_order_is_the_same_request(user_a):
    c, h = user_a
    a = _send(c, h, {"event_type": "x.y", "data": {"a": 1, "b": {"c": 2, "d": 3}}}, key="k1")
    b = c.post("/v1/events", content=b'{"data": {"b": {"d": 3, "c": 2}, "a": 1}, "event_type": "x.y"}',
               headers={**h, "Idempotency-Key": "k1", "Content-Type": "application/json"})
    assert b.status_code == 202 and b.json()["event_id"] == a.json()["event_id"]


def test_reusing_a_key_with_a_different_body_is_a_conflict(user_a):
    c, h = user_a
    original = _send(c, h, key="k1").json()
    r = _send(c, h, {**EVENT, "data": {"order_id": "ORD-999"}}, key="k1")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "idempotency_key_reused"
    assert r.json()["error"]["details"]["event_id"] == original["event_id"]
    assert _count(Event) == 1


def test_idempotency_keys_are_scoped_per_account(user_a, user_b):
    (a, ha), (b, hb) = user_a, user_b
    ea = _send(a, ha, key="shared-key").json()["event_id"]
    eb = _send(b, hb, key="shared-key").json()["event_id"]
    assert ea != eb and _count(Event) == 2


def test_expired_idempotency_key_can_be_reused(user_a):
    c, h = user_a
    first = _send(c, h, key="k1").json()["event_id"]
    with SessionLocal() as db:
        db.execute(update(IdempotencyKey).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        db.commit()
    second = _send(c, h, {**EVENT, "data": {"different": True}}, key="k1")
    assert second.status_code == 202 and second.json()["event_id"] != first
    assert _count(IdempotencyKey) == 1


def test_invalid_idempotency_key_rejected(user_a):
    c, h = user_a
    for bad in ["has space", "x" * 256]:
        r = _send(c, h, key=bad)
        assert r.status_code == 422, bad
    assert _count(Event) == 0


def test_concurrent_requests_with_the_same_key_create_one_event(user_a):
    c, h = user_a
    c.post("/v1/endpoints", json=EP, headers=h)
    user_id = c.get("/v1/auth/me").json()["user"]["id"]
    body = EventIn.model_validate(EVENT)

    def ingest(_):
        with SessionLocal() as db:
            return _ingest(db, user_id, body, "race-key").event.id

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(ingest, range(8)))
    assert len(set(ids)) == 1
    assert _count(Event) == 1 and _count(Delivery) == 1


# --- Outbox ------------------------------------------------------------------

def test_ingestion_writes_and_publishes_outbox_messages(user_a, queued):
    c, h = user_a
    c.post("/v1/endpoints", json=EP, headers=h)
    evt = _send(c, h).json()
    dlv = _deliveries(c, h, evt["event_id"])[0]["id"]
    with SessionLocal() as db:
        [msg] = db.scalars(select(OutboxMessage)).all()
    assert msg.delivery_id == dlv and msg.published_at is not None
    assert _delivery(dlv).enqueued_at is not None
    assert queued == [dlv]
    assert outbox.publish_due() == 0  # nothing left to publish


def test_messages_saved_while_redis_is_down_are_published_later(user_a, queued, monkeypatch):
    c, h = user_a
    c.post("/v1/endpoints", json=EP, headers=h)

    def down(_id):
        raise ConnectionError("redis unreachable")

    monkeypatch.setattr("app.queue.send_delivery", down)
    evt = _send(c, h).json()
    assert evt["delivery_count"] == 1
    assert outbox.publish_due() == 0  # still down

    monkeypatch.setattr("app.queue.send_delivery", queued.append)  # Redis is back
    assert outbox.publish_due() == 1
    assert queued == [_deliveries(c, h, evt["event_id"])[0]["id"]]
    assert outbox.publish_due() == 0


@respx.mock
def test_retries_are_staged_in_the_outbox_and_published_when_due(user_a, queued):
    c, h = user_a
    c.post("/v1/endpoints", json=EP, headers=h)
    dlv = _deliveries(c, h, _send(c, h).json()["event_id"])[0]["id"]
    respx.post(URL).mock(return_value=httpx.Response(503))
    process_delivery(dlv)

    with SessionLocal() as db:
        retry_msg = db.scalars(select(OutboxMessage).where(OutboxMessage.published_at.is_(None))).one()
    assert retry_msg.available_at == _delivery(dlv).next_attempt_at
    assert outbox.publish_due() == 0  # not due yet

    with SessionLocal() as db:
        db.execute(update(OutboxMessage).values(available_at=datetime.now(UTC) - timedelta(seconds=1)))
        db.commit()
    assert outbox.publish_due() == 1 and queued == [dlv, dlv]


def test_sweeper_cleans_old_outbox_messages_and_expired_keys(user_a):
    from app.worker.engine import sweep

    c, h = user_a
    c.post("/v1/endpoints", json=EP, headers=h)
    _send(c, h, key="old")
    _send(c, h, key="fresh")
    long_ago = datetime.now(UTC) - timedelta(days=2)
    with SessionLocal() as db:
        db.execute(update(OutboxMessage).values(published_at=long_ago))
        db.execute(update(IdempotencyKey).where(IdempotencyKey.key == "old").values(expires_at=long_ago))
        db.commit()
    assert sweep()["cleaned"] == 3  # two published messages + one expired key
    with SessionLocal() as db:
        assert db.scalars(select(IdempotencyKey.key)).all() == ["fresh"]
    assert _count(OutboxMessage) == 0 and _count(Event) == 2  # events themselves are kept


# --- Per-endpoint retries ----------------------------------------------------

@respx.mock
def test_endpoint_max_attempts_limits_retries(user_a):
    c, h = user_a
    ep = c.post("/v1/endpoints", json={**EP, "max_attempts": 2}, headers=h).json()
    assert ep["max_attempts"] == 2
    dlv = _deliveries(c, h, _send(c, h).json()["event_id"])[0]
    assert dlv["max_attempts"] == 2

    respx.post(URL).mock(return_value=httpx.Response(500))
    process_delivery(dlv["id"])
    assert _delivery(dlv["id"]).status == "retrying"
    _make_due(dlv["id"])
    process_delivery(dlv["id"])
    d = _delivery(dlv["id"])
    assert d.status == "failed" and d.attempt_count == 2 and "Gave up after 2 attempts" in d.last_error


def test_endpoint_max_attempts_validation_and_update(user_a):
    c, h = user_a
    assert c.post("/v1/endpoints", json={**EP, "max_attempts": 0}, headers=h).status_code == 422
    assert c.post("/v1/endpoints", json={**EP, "max_attempts": 11}, headers=h).status_code == 422
    ep = c.post("/v1/endpoints", json=EP, headers=h).json()
    assert ep["max_attempts"] == get_settings().delivery_max_attempts
    # Existing deliveries keep the limit they started with; new ones use the new limit.
    old = _deliveries(c, h, _send(c, h).json()["event_id"])[0]
    assert c.patch(f"/v1/endpoints/{ep['id']}", json={"max_attempts": 8}, headers=h).json()["max_attempts"] == 8
    new = _deliveries(c, h, _send(c, h, key="second").json()["event_id"])[0]
    assert old["max_attempts"] == 5 and new["max_attempts"] == 8


# --- Replay ------------------------------------------------------------------

@respx.mock
def test_replay_redelivers_the_same_event_and_keeps_history(failed, queued):
    c, h, dlv, event_id, _ = failed
    route = respx.post(URL).mock(return_value=httpx.Response(200))

    r = c.post(f"/v1/deliveries/{dlv}/replay", headers=h)
    assert r.status_code == 202
    body = r.json()
    assert body["delivery"]["id"] == dlv and body["delivery"]["event_id"] == event_id
    assert body["delivery"]["status"] == "pending" and body["delivery"]["replay_count"] == 1
    assert body["delivery"]["replayable"] is False
    assert body["replay"]["previous_status"] == "failed" and body["replay"]["first_attempt_number"] == 2
    assert body["replay"]["requested_by"]["type"] == "api_key"
    assert queued[-1] == dlv
    assert _count(Event) == 1  # no new business event

    assert process_delivery(dlv) == "delivered"
    req = route.calls.last.request
    assert req.headers["HookFlow-Event-Id"] == event_id and req.headers["HookFlow-Attempt"] == "2"

    attempts = c.get(f"/v1/deliveries/{dlv}/attempts", headers=h).json()["data"]
    assert [(a["attempt_number"], a["response_status"]) for a in attempts] == [(1, 400), (2, 200)]
    replays = c.get(f"/v1/deliveries/{dlv}/replays", headers=h).json()["data"]
    assert [x["id"] for x in replays] == [body["replay"]["id"]]


@respx.mock
def test_replay_gets_a_fresh_retry_budget_with_normal_backoff(failed):
    c, h, dlv, _, _ = failed
    c.post(f"/v1/deliveries/{dlv}/replay", headers=h)
    d = _delivery(dlv)
    assert d.max_attempts == 1 + 5 and d.retry_base_attempt == 1

    respx.post(URL).mock(return_value=httpx.Response(503))
    process_delivery(dlv)
    d = _delivery(dlv)
    # First retry after a replay waits ~30s, as for a new delivery, not the long delay of attempt 2+.
    assert d.status == "retrying" and d.next_attempt_at < datetime.now(UTC) + timedelta(seconds=60)
    for _ in range(4):
        _make_due(dlv)
        process_delivery(dlv)
    d = _delivery(dlv)
    assert d.status == "failed" and d.attempt_count == 6 and "Gave up after 5 attempts" in d.last_error


def test_only_failed_or_cancelled_deliveries_can_be_replayed(failed):
    c, h, dlv, _, _ = failed
    assert c.post(f"/v1/deliveries/{dlv}/replay", headers=h).status_code == 202
    # Now pending again: a second request must not stack another replay.
    again = c.post(f"/v1/deliveries/{dlv}/replay", headers=h)
    assert again.status_code == 409 and again.json()["error"]["code"] == "not_replayable"
    assert _delivery(dlv).replay_count == 1


def test_replay_requires_an_enabled_endpoint(failed):
    c, h, dlv, _, ep = failed
    c.patch(f"/v1/endpoints/{ep['id']}", json={"enabled": False}, headers=h)
    r = c.post(f"/v1/deliveries/{dlv}/replay", headers=h)
    assert r.status_code == 409 and "disabled" in r.json()["error"]["message"]
    assert c.get(f"/v1/deliveries/{dlv}", headers=h).json()["replayable"] is False

    c.delete(f"/v1/endpoints/{ep['id']}", headers=h)
    assert "deleted" in c.post(f"/v1/deliveries/{dlv}/replay", headers=h).json()["error"]["message"]


def test_cancelled_delivery_can_be_replayed_after_reenabling(user_a):
    c, h = user_a
    ep = c.post("/v1/endpoints", json=EP, headers=h).json()
    dlv = _deliveries(c, h, _send(c, h).json()["event_id"])[0]["id"]
    c.patch(f"/v1/endpoints/{ep['id']}", json={"enabled": False}, headers=h)
    assert _delivery(dlv).status == "cancelled"
    c.patch(f"/v1/endpoints/{ep['id']}", json={"enabled": True}, headers=h)
    r = c.post(f"/v1/deliveries/{dlv}/replay", headers=h)
    assert r.status_code == 202 and r.json()["replay"]["previous_status"] == "cancelled"


def test_replay_is_rate_limited(failed, monkeypatch):
    c, h, dlv, _, _ = failed
    monkeypatch.setattr(get_settings(), "replay_rate_limit_per_minute", 0)
    r = c.post(f"/v1/deliveries/{dlv}/replay", headers=h)
    assert r.status_code == 429 and "Retry-After" in r.headers
    assert _delivery(dlv).status == "failed"  # nothing changed


@respx.mock
def test_event_replay_replays_only_failed_deliveries(user_a, monkeypatch):
    c, h = user_a
    c.post("/v1/endpoints", json={**EP, "url": "https://good.example.com/in"}, headers=h)
    bad1 = c.post("/v1/endpoints", json=EP, headers=h).json()
    bad2 = c.post("/v1/endpoints", json={**EP, "url": "https://other.example.com/in"}, headers=h).json()
    event_id = _send(c, h).json()["event_id"]
    respx.post("https://good.example.com/in").mock(return_value=httpx.Response(200))
    respx.post(URL).mock(return_value=httpx.Response(400))
    respx.post("https://other.example.com/in").mock(return_value=httpx.Response(410))
    for d in _deliveries(c, h, event_id):
        process_delivery(d["id"])

    # Rate limit counts every delivery: 2 failed deliveries > limit of 1.
    monkeypatch.setattr(get_settings(), "replay_rate_limit_per_minute", 1)
    assert c.post(f"/v1/events/{event_id}/replay", headers=h).status_code == 429
    monkeypatch.setattr(get_settings(), "replay_rate_limit_per_minute", 60)

    only = c.post(f"/v1/events/{event_id}/replay", json={"endpoint_ids": [bad1["id"]]}, headers=h).json()
    assert [x["delivery"]["endpoint_id"] for x in only["replayed"]] == [bad1["id"]]

    rest = c.post(f"/v1/events/{event_id}/replay", headers=h)
    assert rest.status_code == 202
    assert [x["delivery"]["endpoint_id"] for x in rest.json()["replayed"]] == [bad2["id"]]
    skipped = {s["delivery_id"]: s["reason"] for s in rest.json()["skipped"]}
    assert len(skipped) == 2  # the delivered one, and bad1 (already pending again)
    assert _count(Event) == 1 and _count(Delivery) == 3

    nothing = c.post(f"/v1/events/{event_id}/replay", headers=h)
    assert nothing.status_code == 409 and nothing.json()["error"]["code"] == "nothing_to_replay"


def test_replay_tenant_isolation(failed, user_b):
    _, _, dlv, event_id, _ = failed
    b, hb = user_b
    assert b.post(f"/v1/deliveries/{dlv}/replay", headers=hb).status_code == 404
    assert b.post(f"/v1/events/{event_id}/replay", headers=hb).status_code == 404
    assert b.get(f"/v1/deliveries/{dlv}/replays", headers=hb).status_code == 404
    assert _delivery(dlv).status == "failed"


# --- Secret rotation ---------------------------------------------------------

@respx.mock
def test_rotation_grace_period_signs_with_both_secrets(user_a):
    c, h = user_a
    ep = c.post("/v1/endpoints", json=EP, headers=h).json()
    old = ep["signing_secret"]
    rotated = c.post(f"/v1/endpoints/{ep['id']}/rotate-secret", headers=h).json()
    new = rotated["signing_secret"]
    assert new != old and rotated["previous_secret_expires_at"] is not None
    assert c.get(f"/v1/endpoints/{ep['id']}/secret", headers=h).json()["previous_secret_expires_at"]

    route = respx.post(URL).mock(return_value=httpx.Response(200))
    process_delivery(_deliveries(c, h, _send(c, h).json()["event_id"])[0]["id"])
    req = route.calls.last.request
    ts, sig = int(req.headers["HookFlow-Timestamp"]), req.headers["HookFlow-Signature"]
    assert sig.count("v1=") == 2
    assert signing.verify(new, ts, req.content, sig) and signing.verify(old, ts, req.content, sig)

    assert c.get(f"/v1/endpoints/{ep['id']}", headers=h).json()["previous_secret_expires_at"]

    # After the grace period only the new secret signs.
    with SessionLocal() as db:
        db.execute(update(Endpoint).values(previous_secret_expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        db.commit()
    assert c.get(f"/v1/endpoints/{ep['id']}", headers=h).json()["previous_secret_expires_at"] is None
    process_delivery(_deliveries(c, h, _send(c, h, key="2").json()["event_id"])[0]["id"])
    req = route.calls.last.request
    ts, sig = int(req.headers["HookFlow-Timestamp"]), req.headers["HookFlow-Signature"]
    assert sig.count("v1=") == 1 and signing.verify(new, ts, req.content, sig)
    assert not signing.verify(old, ts, req.content, sig)


@respx.mock
def test_rotation_with_no_grace_period_drops_the_old_secret_at_once(user_a):
    c, h = user_a
    ep = c.post("/v1/endpoints", json=EP, headers=h).json()
    r = c.post(f"/v1/endpoints/{ep['id']}/rotate-secret", json={"grace_period_seconds": 0}, headers=h).json()
    assert r["previous_secret_expires_at"] is None
    route = respx.post(URL).mock(return_value=httpx.Response(200))
    process_delivery(_deliveries(c, h, _send(c, h).json()["event_id"])[0]["id"])
    assert route.calls.last.request.headers["HookFlow-Signature"].count("v1=") == 1
    assert c.post(f"/v1/endpoints/{ep['id']}/rotate-secret", json={"grace_period_seconds": -1},
                  headers=h).status_code == 422


# --- Audit log ---------------------------------------------------------------

def test_audit_log_records_important_actions(failed, user_b):
    c, h, dlv, _, ep = failed
    c.get(f"/v1/endpoints/{ep['id']}/secret", headers=h)
    c.post(f"/v1/endpoints/{ep['id']}/rotate-secret", headers=h)
    c.patch(f"/v1/endpoints/{ep['id']}", json={"description": "orders"}, headers=h)
    c.post(f"/v1/deliveries/{dlv}/replay", headers=h)

    logs = c.get("/v1/audit-logs?limit=100", headers=h).json()["data"]
    actions = [x["action"] for x in logs]
    for expected in ["auth.registered", "api_key.created", "endpoint.created", "endpoint.secret_viewed",
                     "endpoint.secret_rotated", "endpoint.updated", "delivery.replayed"]:
        assert expected in actions, expected
    assert logs[0]["action"] == "delivery.replayed" and logs[0]["actor"]["type"] == "api_key"
    assert logs[0]["actor"]["api_key_id"] and logs[0]["resource_id"] == dlv
    updated = next(x for x in logs if x["action"] == "endpoint.updated")
    assert updated["details"]["changes"]["description"] == {"from": None, "to": "orders"}

    # No secrets in audit details.
    secret = c.get(f"/v1/endpoints/{ep['id']}/secret", headers=h).json()["signing_secret"]
    with SessionLocal() as db:
        dumped = str([r.details for r in db.scalars(select(AuditLog)).all()])
    assert "whsec_" not in dumped and secret not in dumped

    filtered = c.get(f"/v1/audit-logs?resource_id={dlv}", headers=h).json()["data"]
    assert [x["action"] for x in filtered] == ["delivery.replayed"]

    b, hb = user_b
    assert all(x["resource_id"] != dlv for x in b.get("/v1/audit-logs", headers=hb).json()["data"])
    assert "delivery.replayed" not in [x["action"] for x in b.get("/v1/audit-logs", headers=hb).json()["data"]]


def test_unchanged_patch_writes_no_audit_entry(user_a):
    c, h = user_a
    ep = c.post("/v1/endpoints", json=EP, headers=h).json()
    c.patch(f"/v1/endpoints/{ep['id']}", json={"event_types": ["order.created"]}, headers=h)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).where(AuditLog.action == "endpoint.updated")) == 0


def test_attempt_rows_are_never_rewritten_by_replay(failed):
    c, h, dlv, _, _ = failed
    with SessionLocal() as db:
        before = [(a.id, a.response_status) for a in db.scalars(select(DeliveryAttempt))]
    c.post(f"/v1/deliveries/{dlv}/replay", headers=h)
    with SessionLocal() as db:
        after = [(a.id, a.response_status) for a in db.scalars(select(DeliveryAttempt))]
    assert before == after
