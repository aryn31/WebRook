"""Customer portal: consumers manage their own endpoints, and can never reach anyone else's data."""

import time
from datetime import timedelta

import httpx
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import portal
from app.db import SessionLocal
from app.models import AuditLog, Delivery
from app.worker.engine import process_delivery

URL_A = "https://ana.example.com/hooks"
URL_B = "https://bob.example.com/hooks"
URL_OWN = "https://shop.example.com/internal"


def new_client() -> TestClient:
    from app.main import app

    return TestClient(app)


def _consumer(c, uid, name=None):
    r = c.post("/v1/consumers", json={"uid": uid, "name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _link(c, uid, **body):
    r = c.post(f"/v1/consumers/{uid}/portal", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _portal(token: str) -> tuple[TestClient, dict]:
    return new_client(), {"Authorization": f"Bearer {token}"}


def _setup(user_a):
    """ShopCo (user A) with consumers ana and bob, each with an endpoint added in their portal."""
    c, h = user_a
    _consumer(c, "ana", "Ana's Bakery")
    _consumer(c, "bob", "Bob's Books")
    ana = _link(c, "ana", brand_name="ShopCo")
    bob = _link(c, "bob")
    pa, ha = _portal(ana["token"])
    pb, hb = _portal(bob["token"])
    ea = pa.post("/v1/portal/endpoints", json={"url": URL_A, "event_types": ["order.*"]}, headers=ha)
    eb = pb.post("/v1/portal/endpoints", json={"url": URL_B}, headers=hb)
    assert ea.status_code == eb.status_code == 201, (ea.text, eb.text)
    own = c.post("/v1/endpoints", json={"url": URL_OWN, "event_types": ["*"]}, headers=h).json()
    return {"c": c, "h": h, "pa": pa, "ha": ha, "pb": pb, "hb": hb, "ea": ea.json(), "eb": eb.json(), "own": own,
            "link": ana}


def test_consumer_crud(user_a):
    c, h = user_a
    a = _consumer(c, "ana-bakery", "Ana's Bakery")
    assert a["id"].startswith("cns_") and a["endpoint_count"] == 0
    assert c.post("/v1/consumers", json={"uid": "ana-bakery"}).status_code == 409
    assert c.post("/v1/consumers", json={"uid": "has space"}).status_code == 422
    assert c.get("/v1/consumers/ana-bakery").json()["name"] == "Ana's Bakery"
    assert c.get(f"/v1/consumers/{a['id']}").json()["uid"] == "ana-bakery"  # by ID too
    assert c.patch("/v1/consumers/ana-bakery", json={"name": "Ana"}).json()["name"] == "Ana"
    assert [x["uid"] for x in c.get("/v1/consumers", headers=h).json()["data"]] == ["ana-bakery"]


def test_portal_link_and_me(user_a):
    s = _setup(user_a)
    assert s["link"]["url"].startswith("http://localhost:3000/portal#token=hfp_")
    me = s["pa"].get("/v1/portal/me", headers=s["ha"]).json()
    assert me["consumer"]["uid"] == "ana" and me["consumer"]["name"] == "Ana's Bakery"
    assert me["brand_name"] == "ShopCo"


@respx.mock
def test_events_go_only_to_the_named_consumer(user_a):
    s = _setup(user_a)
    c, h = s["c"], s["h"]
    for url in (URL_A, URL_B, URL_OWN):
        respx.post(url).mock(return_value=httpx.Response(200))

    r = c.post("/v1/events", json={"event_type": "order.created", "data": {"n": 1}, "consumer": "ana"}, headers=h)
    assert r.status_code == 202 and r.json()["delivery_count"] == 1
    evt = c.get(f"/v1/events/{r.json()['event_id']}", headers=h).json()
    assert evt["consumer_id"] is not None
    [d] = c.get(f"/v1/events/{evt['id']}/deliveries", headers=h).json()["data"]
    assert d["endpoint_id"] == s["ea"]["id"]

    # No consumer: only the account's own endpoints, never consumers'.
    r = c.post("/v1/events", json={"event_type": "order.created", "data": {}}, headers=h)
    [d] = c.get(f"/v1/events/{r.json()['event_id']}/deliveries", headers=h).json()["data"]
    assert d["endpoint_id"] == s["own"]["id"]

    # Unknown consumer is an error, not a silent drop.
    r = c.post("/v1/events", json={"event_type": "x", "data": {}, "consumer": "nobody"}, headers=h)
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_consumer"


@respx.mock
def test_portal_sees_its_deliveries_attempts_and_can_replay(user_a):
    s = _setup(user_a)
    c, h, pa, ha = s["c"], s["h"], s["pa"], s["ha"]
    respx.post(URL_A).mock(side_effect=[httpx.Response(400), httpx.Response(200)])
    r = c.post("/v1/events", json={"event_type": "order.paid", "data": {}, "consumer": "ana"}, headers=h)
    [d] = c.get(f"/v1/events/{r.json()['event_id']}/deliveries", headers=h).json()["data"]
    process_delivery(d["id"])  # 400: fails for good

    rows = pa.get(f"/v1/portal/endpoints/{s['ea']['id']}/deliveries", headers=ha).json()["data"]
    assert [x["id"] for x in rows] == [d["id"]] and rows[0]["status"] == "failed"
    attempts = pa.get(f"/v1/portal/deliveries/{d['id']}/attempts", headers=ha).json()["data"]
    assert attempts[0]["response_status"] == 400
    r = pa.post(f"/v1/portal/deliveries/{d['id']}/replay", headers=ha)
    assert r.status_code == 202 and r.json()["delivery"]["status"] == "pending"
    process_delivery(d["id"])
    with SessionLocal() as db:
        assert db.get(Delivery, d["id"]).status == "delivered"
        row = db.scalar(select(AuditLog).where(AuditLog.action == "delivery.replayed"))
        assert row.actor_type == "portal"


def test_portal_manages_its_endpoints(user_a):
    s = _setup(user_a)
    pa, ha, eid = s["pa"], s["ha"], s["ea"]["id"]
    assert s["ea"]["signing_secret"].startswith("whsec_") and s["ea"]["consumer_id"]
    assert [e["id"] for e in pa.get("/v1/portal/endpoints", headers=ha).json()["data"]] == [eid]
    r = pa.patch(f"/v1/portal/endpoints/{eid}", json={"description": "Orders", "enabled": False}, headers=ha)
    assert r.json()["description"] == "Orders" and r.json()["enabled"] is False
    assert pa.get(f"/v1/portal/endpoints/{eid}/secret", headers=ha).json()["signing_secret"] == s["ea"]["signing_secret"]
    assert pa.delete(f"/v1/portal/endpoints/{eid}", headers=ha).status_code == 204
    assert pa.get("/v1/portal/endpoints", headers=ha).json()["data"] == []


def test_consumers_cannot_reach_each_other_or_the_account(user_a):
    s = _setup(user_a)
    pa, ha = s["pa"], s["ha"]
    for other in (s["eb"]["id"], s["own"]["id"]):
        assert pa.get(f"/v1/portal/endpoints/{other}", headers=ha).status_code == 404
        assert pa.patch(f"/v1/portal/endpoints/{other}", json={"enabled": False}, headers=ha).status_code == 404
        assert pa.delete(f"/v1/portal/endpoints/{other}", headers=ha).status_code == 404
        assert pa.get(f"/v1/portal/endpoints/{other}/secret", headers=ha).status_code == 404
        assert pa.post(f"/v1/portal/endpoints/{other}/security-check", headers=ha).status_code == 404
        assert pa.get(f"/v1/portal/endpoints/{other}/deliveries", headers=ha).status_code == 404
    listed = [e["id"] for e in pa.get("/v1/portal/endpoints", headers=ha).json()["data"]]
    assert listed == [s["ea"]["id"]]


@respx.mock
def test_consumers_cannot_touch_each_others_deliveries(user_a):
    s = _setup(user_a)
    c, h = s["c"], s["h"]
    respx.post(URL_B).mock(return_value=httpx.Response(400))
    r = c.post("/v1/events", json={"event_type": "order.paid", "data": {}, "consumer": "bob"}, headers=h)
    [d] = c.get(f"/v1/events/{r.json()['event_id']}/deliveries", headers=h).json()["data"]
    process_delivery(d["id"])
    assert s["pa"].get(f"/v1/portal/deliveries/{d['id']}/attempts", headers=s["ha"]).status_code == 404
    assert s["pa"].post(f"/v1/portal/deliveries/{d['id']}/replay", headers=s["ha"]).status_code == 404


def test_portal_token_cannot_use_the_normal_api(user_a):
    s = _setup(user_a)
    for path in ("/v1/endpoints", "/v1/events", "/v1/consumers", "/v1/auth/me"):
        assert s["pa"].get(path, headers=s["ha"]).status_code == 401


def test_bad_tokens_are_rejected(user_a):
    s = _setup(user_a)
    token = s["link"]["token"]
    pa = new_client()
    assert pa.get("/v1/portal/me").status_code == 401
    assert pa.get("/v1/portal/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    # Changing the payload (e.g. to another consumer) breaks the signature.
    payload, sig = token[len("hfp_"):].split(".")
    forged = "hfp_" + payload[:-2] + ("AA" if payload[-2:] != "AA" else "BB") + "." + sig
    assert pa.get("/v1/portal/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    # Expired.
    old, _ = portal.create_token(s["c"].get("/v1/auth/me").json()["user"]["id"], s["ea"]["consumer_id"],
                                 timedelta(seconds=-1))
    r = pa.get("/v1/portal/me", headers={"Authorization": f"Bearer {old}"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "portal_link_expired"


def test_another_account_cannot_use_its_consumers(user_a, user_b):
    s = _setup(user_a)
    cb, hb = user_b
    assert cb.post("/v1/consumers/ana/portal", json={}).status_code == 404
    assert cb.get("/v1/consumers/ana").status_code == 404
    r = cb.post("/v1/events", json={"event_type": "x", "data": {}, "consumer": "ana"}, headers=hb)
    assert r.status_code == 422
    assert cb.get("/v1/endpoints", params={"consumer": "ana"}, headers=hb).status_code == 404


def test_deleting_a_consumer_closes_its_portal_and_endpoints(user_a):
    s = _setup(user_a)
    c, h = s["c"], s["h"]
    assert c.get("/v1/endpoints", params={"consumer": "ana"}, headers=h).json()["data"][0]["id"] == s["ea"]["id"]
    assert c.delete("/v1/consumers/ana").status_code == 204
    assert s["pa"].get("/v1/portal/me", headers=s["ha"]).status_code == 401
    assert c.get(f"/v1/endpoints/{s['ea']['id']}", headers=h).status_code == 404  # archived
    # The account's own list never showed consumers' endpoints.
    assert [e["id"] for e in c.get("/v1/endpoints", headers=h).json()["data"]] == [s["own"]["id"]]


def test_consumer_endpoint_limit(user_a, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "max_endpoints_per_consumer", 1)
    s = _setup(user_a)
    r = s["pa"].post("/v1/portal/endpoints", json={"url": "https://ana.example.com/two"}, headers=s["ha"])
    assert r.status_code == 409 and "Each consumer" in r.json()["error"]["message"]


def test_link_needs_endpoint_write(user_a):
    c, h = user_a
    _consumer(c, "ana")
    key = c.post("/v1/api-keys", json={"name": "ro", "scopes": ["endpoints:read"]}).json()["key"]
    r = c.post("/v1/consumers/ana/portal", json={}, headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 403
    assert time.time()  # keep import used
