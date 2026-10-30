from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Delivery, OutboxMessage, User
from tests.conftest import make_user

EP = {"url": "https://hooks.example.com/a", "event_types": ["order.created"]}
EVENT = {"event_type": "order.created", "data": {"order_id": "ORD-101", "amount": 2499}}


# --- Auth --------------------------------------------------------------------

def test_register_login_logout_flow(client):
    make_user(client, "Me@Example.com")
    assert client.get("/v1/auth/me").json()["user"]["email"] == "me@example.com"

    assert client.post("/v1/auth/logout").status_code == 204
    assert client.get("/v1/auth/me").status_code == 401

    r = client.post("/v1/auth/login", json={"email": "me@example.com", "password": "correct-horse-battery"})
    assert r.status_code == 200
    assert client.get("/v1/auth/me").status_code == 200


def test_logout_invalidates_the_session_server_side(client):
    make_user(client)
    token = client.cookies.get("hf_session")
    client.post("/v1/auth/logout")
    client.cookies.set("hf_session", token)  # replaying the old cookie must not work
    assert client.get("/v1/auth/me").status_code == 401


def test_password_is_hashed(client):
    make_user(client)
    with SessionLocal() as db:
        user = db.scalar(select(User))
    assert "correct-horse-battery" not in user.password_hash
    assert user.password_hash.startswith("$argon2")


def test_wrong_password_and_unknown_email_look_the_same(client):
    make_user(client)
    client.post("/v1/auth/logout")
    a = client.post("/v1/auth/login", json={"email": "a@example.com", "password": "wrong-password"})
    b = client.post("/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong-password"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()
    assert a.json()["error"]["code"] == "invalid_credentials"


def test_duplicate_email(client):
    make_user(client)
    r = client.post("/v1/auth/register", json={"email": "A@example.com", "password": "another-password"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"


def test_short_password_rejected_without_echoing_it(client):
    r = client.post("/v1/auth/register", json={"email": "x@example.com", "password": "short"})
    assert r.status_code == 422
    assert "short" not in r.text.replace("string_too_short", "")


def test_login_rate_limited(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_rate_limit_per_minute", 3)
    codes = [
        client.post("/v1/auth/login", json={"email": "a@example.com", "password": "x"}).status_code
        for _ in range(5)
    ]
    assert codes[:3] == [401, 401, 401]
    assert codes[3:] == [429, 429]


def test_protected_routes_require_auth(client):
    for path in ["/v1/endpoints", "/v1/events", "/v1/deliveries", "/v1/stats", "/v1/api-keys"]:
        r = client.get(path)
        assert r.status_code == 401, path
        assert r.json()["error"]["code"] == "unauthorized"


# --- API keys ----------------------------------------------------------------

def test_api_key_lifecycle(user_a):
    c, headers = user_a
    assert c.get("/v1/endpoints", headers=headers).status_code == 200

    keys = c.get("/v1/api-keys").json()["data"]
    assert len(keys) == 1 and "key" not in keys[0] and "key_hash" not in keys[0]
    assert keys[0]["last_used_at"] is not None

    revoked = c.delete(f"/v1/api-keys/{keys[0]['id']}").json()["api_key"]
    assert revoked["revoked_at"] is not None
    assert c.get("/v1/endpoints", headers=headers).status_code == 401


def test_invalid_api_keys_rejected(client):
    for value in ["Bearer nope", "Bearer hf_deadbeef_wrong", "Basic abc"]:
        assert client.get("/v1/endpoints", headers={"Authorization": value}).status_code == 401


def test_api_keys_cannot_manage_api_keys(user_a):
    c, headers = user_a
    c.cookies.clear()
    r = c.get("/v1/api-keys", headers=headers)
    assert r.status_code == 403


# --- Endpoints ---------------------------------------------------------------

def test_endpoint_crud_and_secret(user_a):
    c, h = user_a
    created = c.post("/v1/endpoints", json={**EP, "description": "orders"}, headers=h).json()
    assert created["signing_secret"].startswith("whsec_")
    eid = created["id"]

    got = c.get(f"/v1/endpoints/{eid}", headers=h).json()
    assert "signing_secret" not in got and got["event_types"] == ["order.created"]

    patched = c.patch(f"/v1/endpoints/{eid}", json={"event_types": ["b.two", "a.one"], "enabled": False}, headers=h)
    assert patched.json()["event_types"] == ["a.one", "b.two"] and patched.json()["enabled"] is False

    assert c.get(f"/v1/endpoints/{eid}/secret", headers=h).json()["signing_secret"] == created["signing_secret"]
    rotated = c.post(f"/v1/endpoints/{eid}/rotate-secret", headers=h).json()["signing_secret"]
    assert rotated != created["signing_secret"]
    assert c.get(f"/v1/endpoints/{eid}/secret", headers=h).json()["signing_secret"] == rotated

    assert c.delete(f"/v1/endpoints/{eid}", headers=h).status_code == 204
    assert c.get(f"/v1/endpoints/{eid}", headers=h).status_code == 404
    assert c.get("/v1/endpoints", headers=h).json()["data"] == []


def test_endpoint_validation(user_a):
    c, h = user_a
    assert c.post("/v1/endpoints", json={**EP, "url": "ftp://x.com"}, headers=h).status_code == 422
    assert c.post("/v1/endpoints", json={**EP, "event_types": []}, headers=h).status_code == 422
    assert c.post("/v1/endpoints", json={**EP, "event_types": ["bad type!"]}, headers=h).status_code == 422


def test_endpoint_pagination(user_a):
    c, h = user_a
    ids = [c.post("/v1/endpoints", json=EP, headers=h).json()["id"] for _ in range(5)]
    page1 = c.get("/v1/endpoints?limit=2", headers=h).json()
    page2 = c.get(f"/v1/endpoints?limit=2&cursor={page1['next_cursor']}", headers=h).json()
    page3 = c.get(f"/v1/endpoints?limit=2&cursor={page2['next_cursor']}", headers=h).json()
    seen = [e["id"] for p in (page1, page2, page3) for e in p["data"]]
    assert seen == list(reversed(ids))
    assert page3["next_cursor"] is None


# --- Events ------------------------------------------------------------------

def test_event_creates_deliveries_for_matching_endpoints_only(user_a, queued):
    c, h = user_a
    match = c.post("/v1/endpoints", json=EP, headers=h).json()["id"]
    wildcard = c.post("/v1/endpoints", json={**EP, "event_types": ["*"]}, headers=h).json()["id"]
    c.post("/v1/endpoints", json={**EP, "event_types": ["user.created"]}, headers=h)
    c.post("/v1/endpoints", json={**EP, "enabled": False}, headers=h)

    r = c.post("/v1/events", json=EVENT, headers=h)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "accepted" and body["event_id"].startswith("evt_") and body["delivery_count"] == 2

    deliveries = c.get(f"/v1/events/{body['event_id']}/deliveries", headers=h).json()["data"]
    assert {d["endpoint_id"] for d in deliveries} == {match, wildcard}
    assert all(d["status"] == "pending" and d["attempt_count"] == 0 for d in deliveries)
    assert sorted(queued) == sorted(d["id"] for d in deliveries)

    event = c.get(f"/v1/events/{body['event_id']}", headers=h).json()
    assert event["data"] == EVENT["data"] and event["deliveries"]["pending"] == 2


def test_event_saved_even_if_queue_is_down(user_a, monkeypatch):
    c, h = user_a
    c.post("/v1/endpoints", json=EP, headers=h)

    def broker_down(_id):
        raise ConnectionError("redis unreachable")

    monkeypatch.setattr("app.queue.send_delivery", broker_down)
    r = c.post("/v1/events", json=EVENT, headers=h)
    assert r.status_code == 202
    with SessionLocal() as db:
        d = db.scalar(select(Delivery).where(Delivery.event_id == r.json()["event_id"]))
        assert d is not None
        # The queue message is saved in the outbox, waiting for the publisher.
        [msg] = db.scalars(select(OutboxMessage).where(OutboxMessage.delivery_id == d.id)).all()
        assert msg.published_at is None and msg.publish_attempts == 1 and "unreachable" in msg.last_error


def test_event_validation(user_a):
    c, h = user_a
    assert c.post("/v1/events", json={"event_type": "x", "data": [1]}, headers=h).status_code == 422
    assert c.post("/v1/events", json={"event_type": "bad type", "data": {}}, headers=h).status_code == 422
    r = c.post("/v1/events", content=b"{not json", headers={**h, "content-type": "application/json"})
    assert r.status_code == 422


def test_event_payload_limit(user_a):
    c, h = user_a
    big = {"event_type": "big.one", "data": {"blob": "x" * (1024 * 1024)}}
    r = c.post("/v1/events", json=big, headers=h)
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"


def test_event_list_filters(user_a):
    c, h = user_a
    c.post("/v1/events", json=EVENT, headers=h)
    c.post("/v1/events", json={"event_type": "user.created", "data": {}}, headers=h)
    assert len(c.get("/v1/events", headers=h).json()["data"]) == 2
    only = c.get("/v1/events?event_type=user.created", headers=h).json()["data"]
    assert [e["event_type"] for e in only] == ["user.created"]
    assert c.get("/v1/events?created_after=2999-01-01T00:00:00Z", headers=h).json()["data"] == []


def test_stats(user_a):
    c, h = user_a
    c.post("/v1/endpoints", json=EP, headers=h)
    c.post("/v1/events", json=EVENT, headers=h)
    s = c.get("/v1/stats?range=24h", headers=h).json()
    assert s["events_total"] == 1 and s["deliveries_total"] == 1
    assert s["deliveries_by_status"]["pending"] == 1
    assert sum(b["events"] for b in s["series"]) == 1
    assert len(s["series"]) in (24, 25)


# --- Tenant isolation -------------------------------------------------------

def test_tenant_isolation(user_a, user_b):
    a, ha = user_a
    b, hb = user_b
    ep = a.post("/v1/endpoints", json=EP, headers=ha).json()["id"]
    b.post("/v1/endpoints", json={**EP, "event_types": ["*"]}, headers=hb)
    evt = a.post("/v1/events", json=EVENT, headers=ha).json()
    assert evt["delivery_count"] == 1  # B's wildcard endpoint must not receive A's event
    dlv = a.get(f"/v1/events/{evt['event_id']}/deliveries", headers=ha).json()["data"][0]["id"]

    for method, path in [
        ("get", f"/v1/endpoints/{ep}"),
        ("patch", f"/v1/endpoints/{ep}"),
        ("delete", f"/v1/endpoints/{ep}"),
        ("get", f"/v1/endpoints/{ep}/secret"),
        ("post", f"/v1/endpoints/{ep}/rotate-secret"),
        ("get", f"/v1/events/{evt['event_id']}"),
        ("get", f"/v1/events/{evt['event_id']}/deliveries"),
        ("get", f"/v1/deliveries/{dlv}"),
        ("get", f"/v1/deliveries/{dlv}/attempts"),
    ]:
        kwargs = {"json": {"enabled": False}} if method == "patch" else {}
        r = getattr(b, method)(path, headers=hb, **kwargs)
        assert r.status_code == 404, (method, path, r.status_code)

    assert b.get("/v1/events", headers=hb).json()["data"] == []
    assert b.get("/v1/deliveries", headers=hb).json()["data"] == []
    assert b.get(f"/v1/deliveries?event_id={evt['event_id']}", headers=hb).json()["data"] == []
    assert b.get("/v1/stats", headers=hb).json()["events_total"] == 0
    # A's endpoint is untouched
    assert a.get(f"/v1/endpoints/{ep}", headers=ha).json()["enabled"] is True

    key_a = a.get("/v1/api-keys").json()["data"][0]["id"]
    assert b.delete(f"/v1/api-keys/{key_a}").status_code == 404
