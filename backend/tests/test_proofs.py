"""Proof-of-delivery links: a public page and signed receipt for one delivery."""

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
import respx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import AuditLog, ProofLink
from app.worker.engine import process_delivery

URL = "https://hooks.example.com/in?token=secret123"


def public() -> TestClient:
    from app.main import app

    return TestClient(app)


def _delivered(c, h, route_responses=(503, 200)):
    """An event delivered on attempt 2 (first attempt 503). Returns (delivery, raw body the receiver got)."""
    c.post("/v1/endpoints", json={"url": URL, "event_types": ["*"]}, headers=h)
    route = respx.post(URL).mock(side_effect=[httpx.Response(s) for s in route_responses])
    evt = c.post("/v1/events", json={"event_type": "order.paid", "data": {"total": 4999}}, headers=h).json()
    [d] = c.get(f"/v1/events/{evt['event_id']}/deliveries", headers=h).json()["data"]
    process_delivery(d["id"])
    with SessionLocal() as db:  # make the retry due now
        from app.models import Delivery
        db.execute(update(Delivery).where(Delivery.id == d["id"]).values(next_attempt_at=datetime.now(UTC)))
        db.commit()
    process_delivery(d["id"])
    return d, route.calls.last.request.content


def _token(url: str) -> str:
    return url.rsplit("/", 1)[1]


@respx.mock
def test_proof_page_shows_the_delivery(user_a):
    c, h = user_a
    d, sent = _delivered(c, h)
    r = c.post(f"/v1/deliveries/{d['id']}/proofs", json={"sender_name": "Northwind"}, headers=h)
    assert r.status_code == 201, r.text
    link = r.json()
    assert link["url"].startswith("http://localhost:3000/proof/pod_") and link["active"]

    v = public().get(f"/v1/proof/{link['token']}")
    assert v.status_code == 200, v.text
    p = v.json()
    assert p["status"] == "delivered" and p["sender_name"] == "Northwind"
    assert p["event_type"] == "order.paid" and p["event_id"] == d["event_id"]
    assert p["endpoint_url"] == "https://hooks.example.com/in?…"  # query string hidden
    assert [a["response_status"] for a in p["attempts"]] == [503, 200]
    # The fingerprint matches the exact bytes the receiver got.
    assert p["body_sha256"] == "sha256:" + hashlib.sha256(sent).hexdigest()
    assert p["body"] is None


@respx.mock
def test_body_only_when_asked(user_a):
    c, h = user_a
    d, sent = _delivered(c, h)
    link = c.post(f"/v1/deliveries/{d['id']}/proofs", json={"include_body": True}, headers=h).json()
    assert public().get(f"/v1/proof/{link['token']}").json()["body"] == sent.decode()


@respx.mock
def test_receipt_verifies_and_detects_edits(user_a):
    c, h = user_a
    d, _ = _delivered(c, h)
    link = c.post(f"/v1/deliveries/{d['id']}/proofs", json={}, headers=h).json()
    receipt = public().get(f"/v1/proof/{link['token']}").json()["receipt"]
    key = public().get("/v1/proof/public-key").json()
    assert receipt["key_id"] == key["key_id"] and receipt["algorithm"] == "Ed25519"

    pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(key["public_key"]))
    pub.verify(base64.b64decode(receipt["signature"]), receipt["payload"].encode())
    facts = json.loads(receipt["payload"])
    assert facts["issuer"] == "HookFlow" and facts["status"] == "delivered" and facts["delivery_id"] == d["id"]

    edited = receipt["payload"].replace('"delivered"', '"failed"', 1)
    try:
        pub.verify(base64.b64decode(receipt["signature"]), edited.encode())
        raise AssertionError("an edited receipt verified")
    except InvalidSignature:
        pass


@respx.mock
def test_revoked_expired_and_unknown_links(user_a):
    c, h = user_a
    d, _ = _delivered(c, h)
    a = c.post(f"/v1/deliveries/{d['id']}/proofs", json={}, headers=h).json()
    b = c.post(f"/v1/deliveries/{d['id']}/proofs", json={}, headers=h).json()

    assert c.delete(f"/v1/deliveries/{d['id']}/proofs/{a['id']}", headers=h).status_code == 204
    r = public().get(f"/v1/proof/{a['token']}")
    assert r.status_code == 410 and r.json()["error"]["code"] == "proof_revoked"

    with SessionLocal() as db:
        db.execute(update(ProofLink).where(ProofLink.id == b["id"])
                   .values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        db.commit()
    r = public().get(f"/v1/proof/{b['token']}")
    assert r.status_code == 410 and r.json()["error"]["code"] == "proof_expired"

    for bad in ("pod_nope", "nonsense", "pod_" + "x" * 100):
        r = public().get(f"/v1/proof/{bad}")
        assert r.status_code == 404 and r.json()["error"]["code"] == "proof_not_found"

    rows = c.get(f"/v1/deliveries/{d['id']}/proofs", headers=h).json()["data"]
    assert {x["id"]: x["active"] for x in rows} == {a["id"]: False, b["id"]: False}


@respx.mock
def test_list_counts_views_and_never_returns_the_token(user_a):
    c, h = user_a
    d, _ = _delivered(c, h)
    link = c.post(f"/v1/deliveries/{d['id']}/proofs", json={"expires_in_days": 7}, headers=h).json()
    for _ in range(3):
        public().get(f"/v1/proof/{link['token']}")
    [row] = c.get(f"/v1/deliveries/{d['id']}/proofs", headers=h).json()["data"]
    assert row["view_count"] == 3 and row["last_viewed_at"] is not None
    assert "token" not in row and "url" not in row
    assert row["created_by_email"] == "a@example.com"
    with SessionLocal() as db:
        assert db.scalar(select(ProofLink.token_hash)) != link["token"]  # only a hash is stored
        actions = db.scalars(select(AuditLog.action)).all()
    assert "delivery.proof_shared" in actions


@respx.mock
def test_other_accounts_and_read_only_keys(user_a, user_b):
    c, h = user_a
    d, _ = _delivered(c, h)
    link = c.post(f"/v1/deliveries/{d['id']}/proofs", json={}, headers=h).json()

    cb, hb = user_b
    assert cb.post(f"/v1/deliveries/{d['id']}/proofs", json={}, headers=hb).status_code == 404
    assert cb.get(f"/v1/deliveries/{d['id']}/proofs", headers=hb).status_code == 404
    assert cb.delete(f"/v1/deliveries/{d['id']}/proofs/{link['id']}", headers=hb).status_code == 404

    key = c.post("/v1/api-keys", json={"name": "ro", "scopes": ["deliveries:read"]}).json()["key"]
    ro = {"Authorization": f"Bearer {key}"}
    assert c.get(f"/v1/deliveries/{d['id']}/proofs", headers=ro).status_code == 200
    assert c.post(f"/v1/deliveries/{d['id']}/proofs", json={}, headers=ro).status_code == 403
    assert c.delete(f"/v1/deliveries/{d['id']}/proofs/{link['id']}", headers=ro).status_code == 403


def test_validation(user_a):
    c, h = user_a
    assert c.post("/v1/deliveries/dlv_missing/proofs", json={}, headers=h).status_code == 404
