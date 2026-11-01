from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import select, update

from app import outbox, signing
from app.db import SessionLocal
from app.models import Delivery, DeliveryAttempt
from app.worker.engine import process_delivery, sweep

URL = "https://hooks.example.com/in"


@pytest.fixture
def setup(user_a):
    """One endpoint + one event → returns (client, headers, delivery_id, signing_secret)."""
    c, h = user_a
    ep = c.post("/v1/endpoints", json={"url": URL, "event_types": ["order.created"]}, headers=h).json()
    evt = c.post("/v1/events", json={"event_type": "order.created", "data": {"n": 1}}, headers=h).json()
    dlv = c.get(f"/v1/events/{evt['event_id']}/deliveries", headers=h).json()["data"][0]["id"]
    return c, h, dlv, ep["signing_secret"]


def _delivery(delivery_id: str) -> Delivery:
    with SessionLocal() as db:
        return db.get(Delivery, delivery_id)


def _attempts(delivery_id: str) -> list[DeliveryAttempt]:
    with SessionLocal() as db:
        return list(db.scalars(select(DeliveryAttempt).where(DeliveryAttempt.delivery_id == delivery_id)
                               .order_by(DeliveryAttempt.started_at)))


def _make_due(delivery_id: str) -> None:
    with SessionLocal() as db:
        db.execute(update(Delivery).where(Delivery.id == delivery_id)
                   .values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1)))
        db.commit()


@respx.mock
def test_successful_delivery_is_signed_and_recorded(setup):
    c, h, dlv, secret = setup
    route = respx.post(URL).mock(return_value=httpx.Response(200, text="thanks"))

    assert process_delivery(dlv) == "delivered"

    req = route.calls.last.request
    ts = int(req.headers["HookFlow-Timestamp"])
    assert signing.verify(secret, ts, req.content, req.headers["HookFlow-Signature"])
    assert req.headers["HookFlow-Delivery-Id"] == dlv and req.headers["HookFlow-Attempt"] == "1"
    body = httpx.Response(200, content=req.content).json()
    assert body["type"] == "order.created" and body["data"] == {"n": 1}
    assert body["id"] == req.headers["HookFlow-Event-Id"]

    d = _delivery(dlv)
    assert d.status == "delivered" and d.attempt_count == 1 and d.delivered_at and d.last_status_code == 200
    [a] = _attempts(dlv)
    assert a.success and a.response_status == 200 and a.response_body == "thanks" and a.duration_ms is not None

    api = c.get(f"/v1/deliveries/{dlv}/attempts", headers=h).json()["data"]
    assert api[0]["response_status"] == 200


@respx.mock
def test_retryable_failure_schedules_retry_then_succeeds(setup):
    _, _, dlv, _ = setup
    respx.post(URL).mock(side_effect=[httpx.Response(503), httpx.Response(200)])

    assert process_delivery(dlv) == "failed"
    d = _delivery(dlv)
    assert d.status == "retrying" and d.attempt_count == 1 and d.last_status_code == 503
    assert d.next_attempt_at > datetime.now(UTC) + timedelta(seconds=15)
    assert d.last_error == "Destination returned HTTP 503."

    # Not due yet: a worker picking it up early must do nothing.
    assert process_delivery(dlv) == "skipped"

    _make_due(dlv)
    assert process_delivery(dlv) == "delivered"
    attempts = _attempts(dlv)
    assert [a.response_status for a in attempts] == [503, 200]  # failed attempt still visible
    assert _delivery(dlv).attempt_count == 2


@respx.mock
def test_non_retryable_status_fails_immediately(setup):
    _, _, dlv, _ = setup
    respx.post(URL).mock(return_value=httpx.Response(400, json={"error": "bad"}))
    process_delivery(dlv)
    d = _delivery(dlv)
    assert d.status == "failed" and d.next_attempt_at is None and d.attempt_count == 1


@respx.mock
def test_redirects_are_not_followed(setup):
    _, _, dlv, _ = setup
    route = respx.post(URL).mock(return_value=httpx.Response(302, headers={"Location": "http://169.254.169.254/"}))
    process_delivery(dlv)
    assert route.call_count == 1
    d = _delivery(dlv)
    assert d.status == "failed" and "redirect" in d.last_error.lower()


@respx.mock
def test_timeouts_and_connection_errors_are_retried(setup):
    _, _, dlv, _ = setup
    respx.post(URL).mock(side_effect=[httpx.ReadTimeout("slow"), httpx.ConnectError("refused")])
    process_delivery(dlv)
    assert _delivery(dlv).status == "retrying"
    assert "did not respond" in _delivery(dlv).last_error
    _make_due(dlv)
    process_delivery(dlv)
    assert _delivery(dlv).status == "retrying" and "connect" in _delivery(dlv).last_error


@respx.mock
def test_gives_up_after_max_attempts(setup):
    _, _, dlv, _ = setup
    respx.post(URL).mock(return_value=httpx.Response(500))
    for _ in range(5):
        _make_due(dlv)
        process_delivery(dlv)
    d = _delivery(dlv)
    assert d.status == "failed" and d.attempt_count == 5
    assert "Gave up after 5 attempts" in d.last_error
    assert len(_attempts(dlv)) == 5
    _make_due(dlv)
    assert process_delivery(dlv) == "skipped"


@respx.mock
def test_response_body_is_truncated(setup):
    _, _, dlv, _ = setup
    respx.post(URL).mock(return_value=httpx.Response(200, text="y" * 100_000))
    process_delivery(dlv)
    assert len(_attempts(dlv)[0].response_body) == 4096


@respx.mock
def test_disabled_endpoint_cancels_delivery(setup):
    c, h, dlv, _ = setup
    route = respx.post(URL).mock(return_value=httpx.Response(200))
    endpoint_id = _delivery(dlv).endpoint_id
    # Disable directly in the DB so the API's own cancellation doesn't run first.
    from app.models import Endpoint

    with SessionLocal() as db:
        db.execute(update(Endpoint).where(Endpoint.id == endpoint_id).values(enabled=False))
        db.commit()
    assert process_delivery(dlv) == "cancelled"
    assert route.call_count == 0 and _delivery(dlv).attempt_count == 0


def test_disabling_endpoint_via_api_cancels_unsent_deliveries(setup):
    c, h, dlv, _ = setup
    c.patch(f"/v1/endpoints/{_delivery(dlv).endpoint_id}", json={"enabled": False}, headers=h)
    assert _delivery(dlv).status == "cancelled"


def test_only_one_worker_can_claim(setup):
    _, _, dlv, _ = setup
    from app.worker.engine import _claim

    assert _claim(dlv) == 1
    assert _claim(dlv) is None  # second worker gets nothing
    assert _delivery(dlv).status == "processing"


def test_sweep_requeues_lost_work(setup, queued):
    _, _, dlv, _ = setup
    assert queued == [dlv]  # published by the API right after commit
    assert sweep()["requeued"] == 0  # just published; don't double-queue

    # Simulate the published message being lost in Redis a while ago.
    with SessionLocal() as db:
        db.execute(update(Delivery).where(Delivery.id == dlv)
                   .values(enqueued_at=datetime.now(UTC) - timedelta(minutes=5)))
        db.commit()
    assert sweep()["requeued"] == 1
    assert sweep()["requeued"] == 0  # a fresh message is already waiting in the outbox
    assert outbox.publish_due() == 1 and queued == [dlv, dlv]


@respx.mock
def test_sweep_recovers_crashed_worker(setup):
    _, _, dlv, _ = setup
    from app.worker.engine import _claim

    _claim(dlv)  # a worker claims it... and dies
    with SessionLocal() as db:
        db.execute(update(Delivery).where(Delivery.id == dlv)
                   .values(locked_until=datetime.now(UTC) - timedelta(seconds=1)))
        db.commit()

    assert sweep() == {"reclaimed": 1, "requeued": 0, "cleaned": 0, "expired": 0}
    assert outbox.publish_due() == 1  # the retry was staged in the outbox in the same transaction
    d = _delivery(dlv)
    assert d.status == "retrying" and d.attempt_count == 1
    [lost] = _attempts(dlv)
    assert not lost.success and "worker stopped" in lost.error.lower()

    respx.post(URL).mock(return_value=httpx.Response(200))
    assert process_delivery(dlv) == "delivered"
    assert _delivery(dlv).attempt_count == 2


def test_late_result_after_lease_lost_does_not_overwrite_state(setup):
    _, _, dlv, _ = setup
    from app.worker.engine import Outcome, _claim, _record

    _claim(dlv)
    with SessionLocal() as db:
        db.execute(update(Delivery).where(Delivery.id == dlv)
                   .values(locked_until=datetime.now(UTC) - timedelta(seconds=1)))
        db.commit()
    sweep()  # reclaimed → retrying
    _record(dlv, 1, datetime.now(UTC), 5, Outcome(success=True, retryable=False, status_code=200))
    assert _delivery(dlv).status == "retrying"
    assert len(_attempts(dlv)) == 2  # both the lost-worker record and the late real result are kept
