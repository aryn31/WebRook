from datetime import datetime, timezone

import pytest

import hookflow
from hookflow import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    ConflictError,
    HookFlow,
    HookFlowError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ValidationError,
)

from conftest import error_body

KEY = "hf_ab12cd34_secretsecret"


@pytest.fixture
def client(stub):
    return HookFlow(KEY, base_url=stub.base_url + "/", timeout=5, max_retries=2)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr("hookflow.client._sleep", sleeps.append)
    return sleeps


ACCEPTED = {"event_id": "evt_1", "status": "accepted", "created_at": "2026-10-30T12:00:00Z", "delivery_count": 2}


def test_requires_api_key(monkeypatch):
    monkeypatch.delenv("HOOKFLOW_API_KEY", raising=False)
    with pytest.raises(ValueError):
        HookFlow()
    monkeypatch.setenv("HOOKFLOW_API_KEY", "hf_env_key")
    monkeypatch.setenv("HOOKFLOW_BASE_URL", "https://hooks.example.com/")
    c = HookFlow()
    assert c.api_key == "hf_env_key" and c.base_url == "https://hooks.example.com"


def test_send_event(stub, client):
    stub.reply((202, ACCEPTED))
    result = client.events.send("order.created", {"order_id": "ORD-1", "name": "café"})
    assert result == ACCEPTED
    req = stub.last
    assert req.method == "POST" and req.path == "/v1/events"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert req.headers["content-type"] == "application/json"
    assert req.headers["user-agent"].startswith("hookflow-python/")
    assert "idempotency-key" not in req.headers
    assert req.json == {"event_type": "order.created", "data": {"order_id": "ORD-1", "name": "café"}}


def test_send_event_with_idempotency_key(stub, client):
    stub.reply((202, ACCEPTED, {"Idempotent-Replayed": "true"}))
    client.events.send("order.created", {"a": 1}, idempotency_key="order-ORD-1-created")
    assert stub.last.headers["idempotency-key"] == "order-ORD-1-created"


def test_send_without_key_is_never_retried(stub, client, no_sleep):
    stub.reply((503, error_body("service_unavailable", "Down"), {"Retry-After": "1"}))
    with pytest.raises(InternalServerError) as info:
        client.events.send("order.created", {})
    assert len(stub.requests) == 1 and no_sleep == []
    assert info.value.retry_after == 1


def test_send_with_key_retried_on_429_then_5xx(stub, client, no_sleep):
    stub.reply(
        (429, error_body("rate_limited", "Slow down"), {"Retry-After": "2"}),
        (500, error_body("internal_error", "Oops")),
        (202, ACCEPTED),
    )
    assert client.events.send("order.created", {}, idempotency_key="k1") == ACCEPTED
    assert len(stub.requests) == 3
    assert all(r.headers["idempotency-key"] == "k1" for r in stub.requests)
    assert no_sleep[0] == 2  # honours Retry-After
    assert len(no_sleep) == 2


def test_retries_exhausted(stub, client):
    stub.handler = lambda req: (502, b"Bad Gateway")
    with pytest.raises(InternalServerError) as info:
        client.events.get("evt_1")
    assert len(stub.requests) == 3  # first try + max_retries
    assert info.value.status == 502 and info.value.message == "Bad Gateway" and info.value.code is None


def test_long_retry_after_is_not_waited(stub, client, no_sleep):
    stub.reply((429, error_body("quota_exceeded", "Daily quota"), {"Retry-After": "40000"}))
    with pytest.raises(RateLimitError) as info:
        client.events.list()
    assert len(stub.requests) == 1 and no_sleep == []
    assert info.value.retry_after == 40000 and info.value.code == "quota_exceeded"


def test_max_retries_zero(stub):
    c = HookFlow(KEY, base_url=stub.base_url, max_retries=0)
    stub.reply((503, error_body("service_unavailable", "Down")))
    with pytest.raises(InternalServerError):
        c.deliveries.get("dlv_1")
    assert len(stub.requests) == 1


def test_post_and_patch_not_retried(stub, client):
    stub.handler = lambda req: (500, error_body("internal_error", "x"))
    with pytest.raises(InternalServerError):
        client.deliveries.replay("dlv_1")
    with pytest.raises(InternalServerError):
        client.endpoints.update("ep_1", enabled=False)
    assert len(stub.requests) == 2


@pytest.mark.parametrize(
    "status,code,cls",
    [
        (400, "bad_request", hookflow.BadRequestError),
        (401, "unauthorized", AuthenticationError),
        (403, "forbidden", PermissionDeniedError),
        (404, "not_found", NotFoundError),
        (409, "idempotency_key_reused", ConflictError),
        (413, "payload_too_large", hookflow.PayloadTooLargeError),
        (422, "validation_error", ValidationError),
        (429, "rate_limited", RateLimitError),
        (418, "error", HookFlowError),
    ],
)
def test_error_mapping(stub, client, status, code, cls):
    details = [{"loc": ["body", "event_type"], "msg": "bad", "type": "value_error"}]
    stub.handler = lambda req: (status, error_body(code, "Something failed.", details), {"Retry-After": "0"})
    with pytest.raises(cls) as info:
        client.events.send("order.created", {})
    err = info.value
    assert isinstance(err, HookFlowError)
    assert (err.status, err.code, err.message, err.details) == (status, code, "Something failed.", details)
    assert str(err) == f"[{status} {code}] Something failed."


def test_permission_denied_is_an_authentication_error():
    assert issubclass(PermissionDeniedError, AuthenticationError)


def test_connection_error():
    c = HookFlow(KEY, base_url="http://127.0.0.1:9", max_retries=0)  # discard port: nothing listens
    with pytest.raises(APIConnectionError) as info:
        c.events.get("evt_1")
    assert info.value.status is None


def test_timeout(stub):
    import time as _time

    def slow(req):
        _time.sleep(0.5)
        return (200, {})

    stub.handler = slow
    c = HookFlow(KEY, base_url=stub.base_url, timeout=0.1, max_retries=0)
    with pytest.raises(APITimeoutError):
        c.events.get("evt_1")


def test_events_list_query_and_pagination(stub, client):
    pages = {
        None: {"data": [{"id": "evt_3"}, {"id": "evt_2"}], "next_cursor": "evt_2"},
        "evt_2": {"data": [{"id": "evt_1"}], "next_cursor": None},
    }
    stub.handler = lambda req: (200, pages[req.query.get("cursor", [None])[0]])
    after = datetime(2026, 10, 1, tzinfo=timezone.utc)
    page = client.events.list(event_type="order.created", created_after=after, limit=2)
    assert [e["id"] for e in page] == ["evt_3", "evt_2"]
    assert page.has_more and page.next_cursor == "evt_2"
    q = stub.requests[0].query
    assert q == {"event_type": ["order.created"], "created_after": ["2026-10-01T00:00:00+00:00"], "limit": ["2"]}

    ids = [e["id"] for e in client.events.list_all(event_type="order.created", limit=2)]
    assert ids == ["evt_3", "evt_2", "evt_1"]
    last = stub.last.query
    assert last["cursor"] == ["evt_2"] and last["event_type"] == ["order.created"] and last["limit"] == ["2"]


def test_auto_paging_is_lazy(stub, client):
    stub.handler = lambda req: (200, {"data": [{"id": "x"}], "next_cursor": "more"})
    it = client.deliveries.list_all(status="failed")
    assert next(it)["id"] == "x"
    assert len(stub.requests) == 1
    next(it)
    assert len(stub.requests) == 2


def test_event_endpoints(stub, client):
    stub.handler = lambda req: (200, {"data": [{"id": "dlv_1"}]} if req.path.endswith("deliveries") else {"id": "evt_1"})
    assert client.events.get("evt_1") == {"id": "evt_1"}
    assert stub.last.path == "/v1/events/evt_1"
    assert client.events.deliveries("evt_1") == [{"id": "dlv_1"}]
    assert stub.last.path == "/v1/events/evt_1/deliveries"


def test_event_replay(stub, client):
    stub.handler = lambda req: (202, {"replayed": [], "skipped": []})
    client.events.replay("evt_1")
    assert stub.last.method == "POST" and stub.last.path == "/v1/events/evt_1/replay" and stub.last.json == {}
    client.events.replay("evt_1", endpoint_ids=["ep_1", "ep_2"])
    assert stub.last.json == {"endpoint_ids": ["ep_1", "ep_2"]}


def test_nothing_to_replay(stub, client):
    skipped = [{"delivery_id": "dlv_1", "reason": "Delivery is delivered."}]
    stub.reply((409, error_body("nothing_to_replay", "None of this event's deliveries can be replayed.", skipped)))
    with pytest.raises(ConflictError) as info:
        client.events.replay("evt_1")
    assert info.value.code == "nothing_to_replay" and info.value.details == skipped


def test_delivery_endpoints(stub, client):
    stub.handler = lambda req: (202 if req.method == "POST" else 200, {"data": [{"attempt_number": 1}]})
    assert client.deliveries.attempts("dlv_1") == [{"attempt_number": 1}]
    assert stub.last.path == "/v1/deliveries/dlv_1/attempts"
    client.deliveries.replays("dlv_1")
    assert stub.last.path == "/v1/deliveries/dlv_1/replays"
    client.deliveries.get("dlv_1")
    assert stub.last.path == "/v1/deliveries/dlv_1"
    client.deliveries.replay("dlv_1")
    assert (stub.last.method, stub.last.path) == ("POST", "/v1/deliveries/dlv_1/replay")
    client.deliveries.list(status="failed", endpoint_id="ep_1", event_id="evt_1", limit=10, cursor="dlv_9")
    assert stub.last.query == {
        "status": ["failed"], "endpoint_id": ["ep_1"], "event_id": ["evt_1"], "limit": ["10"], "cursor": ["dlv_9"]
    }


def test_ids_are_path_escaped(stub, client):
    stub.handler = lambda req: (200, {})
    client.deliveries.get("../endpoints/x")
    assert stub.last.path == "/v1/deliveries/..%2Fendpoints%2Fx"
    with pytest.raises(ValueError):
        client.deliveries.get("")


def test_bulk_replay_defaults_and_full_body(stub, client):
    result = {"matched": 3, "replayed": ["dlv_1", "dlv_2"], "skipped": [{"delivery_id": "dlv_3", "reason": "x"}],
              "has_more": False, "dry_run": False}
    stub.handler = lambda req: (202, result)
    assert client.deliveries.bulk_replay() == result
    assert (stub.last.method, stub.last.path, stub.last.json) == ("POST", "/v1/deliveries/replay", {})

    client.deliveries.bulk_replay(
        endpoint_id="ep_1",
        event_type="order.created",
        statuses=["failed", "cancelled"],
        created_after=datetime(2026, 10, 1, tzinfo=timezone.utc),
        created_before="2026-10-02T00:00:00Z",
        limit=500,
        dry_run=True,
    )
    assert stub.last.json == {
        "endpoint_id": "ep_1",
        "event_type": "order.created",
        "statuses": ["failed", "cancelled"],
        "created_after": "2026-10-01T00:00:00+00:00",
        "created_before": "2026-10-02T00:00:00Z",
        "limit": 500,
        "dry_run": True,
    }


def test_bulk_replay_not_retried(stub, client):
    stub.handler = lambda req: (503, error_body("service_unavailable", "down"), {"Retry-After": "1"})
    with pytest.raises(InternalServerError):
        client.deliveries.bulk_replay(dry_run=False)
    assert len(stub.requests) == 1


def test_endpoints_crud(stub, client):
    ep = {"id": "ep_1", "url": "https://example.com/hooks", "event_types": ["*"]}

    def handler(req):
        if req.method == "DELETE":
            return (204, None)
        if req.method == "POST":
            return (201, {**ep, "signing_secret": "whsec_abc"})
        if req.path == "/v1/endpoints":
            return (200, {"data": [ep], "next_cursor": None})
        return (200, ep)

    stub.handler = handler
    created = client.endpoints.create("https://example.com/hooks", ["*"], description="Main", max_attempts=3)
    assert created["signing_secret"] == "whsec_abc"
    assert stub.last.json == {"url": "https://example.com/hooks", "event_types": ["*"], "description": "Main",
                              "max_attempts": 3}

    assert list(client.endpoints.list()) == [ep]
    assert [e["id"] for e in client.endpoints.list_all()] == ["ep_1"]
    assert client.endpoints.get("ep_1") == ep

    client.endpoints.update("ep_1", enabled=False, description=None)
    assert (stub.last.method, stub.last.path) == ("PATCH", "/v1/endpoints/ep_1")
    assert stub.last.json == {"enabled": False, "description": None}

    assert client.endpoints.delete("ep_1") is None
    assert (stub.last.method, stub.last.path) == ("DELETE", "/v1/endpoints/ep_1")

    client.endpoints.secret("ep_1")
    assert stub.last.path == "/v1/endpoints/ep_1/secret"
    client.endpoints.rotate_secret("ep_1", grace_period_seconds=0)
    assert stub.last.path == "/v1/endpoints/ep_1/rotate-secret" and stub.last.json == {"grace_period_seconds": 0}


def test_endpoint_retry_schedule(stub, client):
    stub.handler = lambda req: (201 if req.method == "POST" else 200, {"id": "ep_1"})
    client.endpoints.create("https://example.com/h", ["order.created"], retry_schedule=(10, 60, 300))
    assert stub.last.json["retry_schedule"] == [10, 60, 300]
    client.endpoints.update("ep_1", retry_schedule=None)
    assert stub.last.json == {"retry_schedule": None}
    client.endpoints.update("ep_1", retry_schedule=[5])
    assert stub.last.json == {"retry_schedule": [5]}
