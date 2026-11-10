"""Standard Webhooks signatures, checked with the official library."""

import secrets
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import update
from standardwebhooks import Webhook
from standardwebhooks.webhooks import WebhookVerificationError

from app import signing
from app.db import SessionLocal
from app.models import Delivery, Endpoint
from app.security import encrypt_secret
from app.worker.engine import process_delivery

URL = "https://hooks.example.com/in"


def _std_headers(request: httpx.Request) -> dict[str, str]:
    return {k: request.headers[k] for k in ("webhook-id", "webhook-timestamp", "webhook-signature")}


def _send(c, h, **endpoint):
    ep = c.post("/v1/endpoints", json={"url": URL, "event_types": ["*"], **endpoint}, headers=h).json()
    evt = c.post("/v1/events", json={"event_type": "order.paid", "data": {"total": 4999}}, headers=h).json()
    dlv = c.get(f"/v1/events/{evt['event_id']}/deliveries", headers=h).json()["data"][0]["id"]
    return ep, evt["event_id"], dlv


@respx.mock
def test_requests_verify_with_the_official_library(user_a):
    c, h = user_a
    route = respx.post(URL).mock(return_value=httpx.Response(200))
    ep, event_id, dlv = _send(c, h)
    assert ep["signing_secret"].startswith("whsec_") and ep["secret_format"] == "standard"
    assert signing.is_standard_secret(ep["signing_secret"])
    process_delivery(dlv)

    req = route.calls.last.request
    payload = Webhook(ep["signing_secret"]).verify(req.content, _std_headers(req))
    assert payload["data"] == {"total": 4999}
    assert req.headers["webhook-id"] == event_id  # stable: receivers dedupe on it
    assert req.headers["webhook-timestamp"] == req.headers["HookFlow-Timestamp"]
    # HookFlow's own signature is still there for existing receivers.
    assert signing.verify(ep["signing_secret"], int(req.headers["HookFlow-Timestamp"]), req.content,
                          req.headers["HookFlow-Signature"])
    # And a wrong secret fails the official check.
    with pytest.raises(WebhookVerificationError):
        Webhook(signing.PREFIX + "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFB").verify(req.content, _std_headers(req))


@respx.mock
def test_webhook_id_is_the_same_on_retries(user_a):
    c, h = user_a
    route = respx.post(URL).mock(side_effect=[httpx.Response(503), httpx.Response(200)])
    _, event_id, dlv = _send(c, h)
    process_delivery(dlv)
    with SessionLocal() as db:
        db.execute(update(Delivery).where(Delivery.id == dlv).values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1)))
        db.commit()
    process_delivery(dlv)
    ids = {call.request.headers["webhook-id"] for call in route.calls}
    assert ids == {event_id}


@respx.mock
def test_both_secrets_sign_during_rotation(user_a):
    c, h = user_a
    route = respx.post(URL).mock(return_value=httpx.Response(200))
    ep = c.post("/v1/endpoints", json={"url": URL, "event_types": ["*"]}, headers=h).json()
    new = c.post(f"/v1/endpoints/{ep['id']}/rotate-secret", json={"grace_period_seconds": 3600}, headers=h).json()
    evt = c.post("/v1/events", json={"event_type": "order.paid", "data": {}}, headers=h).json()
    process_delivery(c.get(f"/v1/events/{evt['event_id']}/deliveries", headers=h).json()["data"][0]["id"])
    req = route.calls.last.request
    assert req.headers["webhook-signature"].count("v1,") == 2
    Webhook(ep["signing_secret"]).verify(req.content, _std_headers(req))  # old secret still verifies
    Webhook(new["signing_secret"]).verify(req.content, _std_headers(req))  # and so does the new one


def test_older_secrets_are_flagged_and_rotation_fixes_them(user_a):
    c, h = user_a
    ep = c.post("/v1/endpoints", json={"url": URL, "event_types": ["*"]}, headers=h).json()
    legacy = f"whsec_{secrets.token_urlsafe(32)}"  # how secrets were made before
    while signing.is_standard_secret(legacy):
        legacy = f"whsec_{secrets.token_urlsafe(32)}"
    with SessionLocal() as db:
        db.execute(update(Endpoint).where(Endpoint.id == ep["id"]).values(secret_encrypted=encrypt_secret(legacy)))
        db.commit()
    assert c.get(f"/v1/endpoints/{ep['id']}", headers=h).json()["secret_format"] == "legacy"
    c.post(f"/v1/endpoints/{ep['id']}/rotate-secret", json={"grace_period_seconds": 0}, headers=h)
    assert c.get(f"/v1/endpoints/{ep['id']}", headers=h).json()["secret_format"] == "standard"


@respx.mock
def test_security_check_tests_standard_receivers_too(user_a):
    c, h = user_a
    ep = c.post("/v1/endpoints", json={"url": URL, "event_types": ["*"]}, headers=h).json()
    wh = Webhook(ep["signing_secret"])

    def standard_receiver(request: httpx.Request) -> httpx.Response:
        try:
            wh.verify(request.content, {k: request.headers.get(k, "") for k in
                                        ("webhook-id", "webhook-timestamp", "webhook-signature")})
        except WebhookVerificationError:
            return httpx.Response(401)
        return httpx.Response(204)

    respx.post(URL).mock(side_effect=standard_receiver)
    sc = c.post(f"/v1/endpoints/{ep['id']}/security-check", headers=h).json()["security_check"]
    assert sc["verdict"] == "pass", sc


def test_signing_matches_the_library_exactly():
    secret = "whsec_" + "MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"
    ts = int(datetime.now(UTC).timestamp())
    body = b'{"type":"order.paid"}'
    ours = signing.sign_standard(secret, "evt_1", ts, body)
    theirs = Webhook(secret).sign("evt_1", datetime.fromtimestamp(ts, UTC), body.decode())
    assert ours == theirs
