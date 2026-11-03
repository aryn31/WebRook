import importlib.util
import re
import time
from datetime import datetime, timezone
UTC = timezone.utc

import pytest

import hookflow
from hookflow import WebhookVerificationError, verify, verify_signature

from conftest import API_DOCS, BACKEND_SIGNING, backend_sign, build_body

SECRET = "whsec_9f8e7d6c5b4a39281706f5e4d3c2b1a0"
OLD_SECRET = "whsec_old0000000000000000000000000000"
NOW = 1_793_361_600
BODY = build_body(
    "evt_01JABCDEF", "order.created", datetime(2026, 10, 30, 12, 0, tzinfo=UTC),
    {"order_id": "ORD-101", "customer": "Zoë", "note": "café ☕", "total": 12.5},
)


def headers_for(body=BODY, secrets=(SECRET,), ts=NOW):
    return {
        "Content-Type": "application/json",
        "HookFlow-Event-Id": "evt_01JABCDEF",
        "HookFlow-Event-Type": "order.created",
        "HookFlow-Delivery-Id": "dlv_01JABCDEF",
        "HookFlow-Attempt": "1",
        "HookFlow-Timestamp": str(ts),
        "HookFlow-Signature": ",".join(backend_sign(s, ts, body) for s in secrets),
    }


def expect_reason(reason, *args, **kwargs):
    with pytest.raises(WebhookVerificationError) as info:
        verify(*args, **kwargs)
    assert info.value.reason == reason
    return info.value


def test_valid_returns_parsed_event():
    event = verify(BODY, headers_for(), SECRET, now=NOW)
    assert event["id"] == "evt_01JABCDEF"
    assert event["type"] == "order.created"
    assert event["created_at"] == "2026-10-30T12:00:00.000000Z"
    assert event["data"]["note"] == "café ☕"


def test_str_payload_is_utf8():
    assert verify(BODY.decode("utf-8"), headers_for(), SECRET, now=NOW)["data"]["customer"] == "Zoë"


def test_uses_real_clock_by_default():
    ts = int(time.time())
    assert verify(BODY, headers_for(ts=ts), SECRET)["id"] == "evt_01JABCDEF"


def test_tampered_body():
    tampered = BODY.replace(b"ORD-101", b"ORD-999")
    expect_reason("signature_mismatch", tampered, headers_for(), SECRET, now=NOW)


def test_reserialized_json_fails():
    import json

    reserialized = json.dumps(json.loads(BODY)).encode()  # different whitespace / escaping
    assert reserialized != BODY
    expect_reason("signature_mismatch", reserialized, headers_for(), SECRET, now=NOW)


def test_wrong_secret():
    expect_reason("signature_mismatch", BODY, headers_for(), "whsec_wrong", now=NOW)


def test_secret_without_prefix_does_not_match():
    expect_reason("signature_mismatch", BODY, headers_for(), SECRET.removeprefix("whsec_"), now=NOW)


def test_tampered_timestamp():
    h = headers_for()
    h["HookFlow-Timestamp"] = str(NOW + 1)
    expect_reason("signature_mismatch", BODY, h, SECRET, now=NOW)


@pytest.mark.parametrize("offset", [301, -301, 10_000])
def test_timestamp_outside_tolerance(offset):
    expect_reason("timestamp_out_of_tolerance", BODY, headers_for(ts=NOW + offset), SECRET, now=NOW)


@pytest.mark.parametrize("offset", [300, -300, 0])
def test_timestamp_at_tolerance_edge(offset):
    assert verify(BODY, headers_for(ts=NOW + offset), SECRET, now=NOW)


def test_custom_tolerance():
    h = headers_for(ts=NOW - 50)
    expect_reason("timestamp_out_of_tolerance", BODY, h, SECRET, tolerance_seconds=10, now=NOW)
    assert verify(BODY, h, SECRET, tolerance_seconds=60, now=NOW)


def test_rotation_two_signatures_either_secret_verifies():
    h = headers_for(secrets=(SECRET, OLD_SECRET))
    assert h["HookFlow-Signature"].count("v1=") == 2
    assert verify(BODY, h, SECRET, now=NOW)
    assert verify(BODY, h, OLD_SECRET, now=NOW)
    expect_reason("signature_mismatch", BODY, h, "whsec_neither", now=NOW)


def test_signature_with_spaces_and_unknown_schemes():
    sig = backend_sign(SECRET, NOW, BODY)
    h = headers_for()
    h["HookFlow-Signature"] = f"v0=deadbeef, {sig} ,v2=abc"
    assert verify(BODY, h, SECRET, now=NOW)


def test_case_insensitive_headers():
    lower = {k.lower(): v for k, v in headers_for().items()}
    upper = {k.upper(): v for k, v in headers_for().items()}
    pairs = list(headers_for().items())
    assert verify(BODY, lower, SECRET, now=NOW)
    assert verify(BODY, upper, SECRET, now=NOW)
    assert verify(BODY, pairs, SECRET, now=NOW)
    # WSGI/ASGI style byte headers
    assert verify(BODY, [(k.lower().encode(), v.encode()) for k, v in pairs], SECRET, now=NOW)


@pytest.mark.parametrize("missing", ["HookFlow-Timestamp", "HookFlow-Signature"])
def test_missing_headers(missing):
    h = headers_for()
    del h[missing]
    err = expect_reason("missing_header", BODY, h, SECRET, now=NOW)
    assert missing in str(err)


@pytest.mark.parametrize("value", ["", "abc", "1793361600.5", "-1793361600", "１２３"])
def test_invalid_timestamp(value):
    h = headers_for()
    h["HookFlow-Timestamp"] = value
    expect_reason("invalid_timestamp", BODY, h, SECRET, now=NOW)


@pytest.mark.parametrize("value", ["", "deadbeef", "v2=abc", "sha256=abc"])
def test_no_v1_signatures(value):
    h = headers_for()
    h["HookFlow-Signature"] = value
    expect_reason("no_signatures", BODY, h, SECRET, now=NOW)


def test_non_ascii_signature_does_not_crash():
    h = headers_for()
    h["HookFlow-Signature"] = "v1=é" + "0" * 63
    expect_reason("signature_mismatch", BODY, h, SECRET, now=NOW)


def test_parsed_payload_must_be_json_object():
    body = b"[1,2,3]"
    expect_reason("invalid_payload", body, headers_for(body=body), SECRET, now=NOW)
    body = b"not json"
    expect_reason("invalid_payload", body, headers_for(body=body), SECRET, now=NOW)


def test_dict_payload_rejected_with_helpful_message():
    with pytest.raises(TypeError, match="raw request body"):
        verify({"id": "evt"}, headers_for(), SECRET, now=NOW)


def test_empty_secret_rejected():
    with pytest.raises(ValueError):
        verify(BODY, headers_for(), "", now=NOW)


def test_verify_signature_does_not_parse():
    body = b"not json at all"
    assert verify_signature(body, headers_for(body=body), SECRET, now=NOW) is None


def test_sign_helper_matches_backend():
    assert hookflow.sign(SECRET, NOW, BODY) == backend_sign(SECRET, NOW, BODY)


# --- Cross-checks against the real backend source and the docs -----------------------------------------

@pytest.mark.skipif(not BACKEND_SIGNING.exists(), reason="backend/app/signing.py not present")
def test_cross_check_backend_signing_module():
    """Load backend/app/signing.py as a standalone module (it only uses hashlib/hmac) and compare."""
    spec = importlib.util.spec_from_file_location("_hookflow_backend_signing", BACKEND_SIGNING)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    for secrets in [(SECRET,), (SECRET, OLD_SECRET)]:
        header = ",".join(mod.sign(s, NOW, BODY) for s in secrets)
        h = headers_for(secrets=secrets)
        assert h["HookFlow-Signature"] == header
        for s in secrets:
            assert verify(BODY, h, s, now=NOW)
            assert mod.verify(s, NOW, BODY, header)  # backend agrees too
    assert hookflow.sign(SECRET, NOW, BODY) == mod.sign(SECRET, NOW, BODY)


@pytest.mark.skipif(not API_DOCS.exists(), reason="docs/api.md not present")
def test_cross_check_docs_python_snippet(monkeypatch):
    """Run the hand-written snippet from docs/api.md and check it agrees with the SDK."""
    docs = API_DOCS.read_text()
    section = docs.split("### Verifying the signature", 1)[1]
    snippet = re.search(r"```python\n(.*?)```", section, re.S).group(1)
    ns: dict = {}
    exec(snippet, ns)
    docs_verify = ns["verify"]
    monkeypatch.setattr(time, "time", lambda: NOW)

    cases = [
        (BODY, headers_for(), SECRET),
        (BODY, headers_for(secrets=(SECRET, OLD_SECRET)), OLD_SECRET),
        (BODY.replace(b"101", b"102"), headers_for(), SECRET),
        (BODY, headers_for(), "whsec_wrong"),
        (BODY, headers_for(ts=NOW - 301), SECRET),
        (BODY, headers_for(ts=NOW + 299), SECRET),
    ]
    for body, h, secret in cases:
        expected = docs_verify(secret, body, h["HookFlow-Timestamp"], h["HookFlow-Signature"])
        try:
            verify(body, h, secret)
            ours = True
        except WebhookVerificationError:
            ours = False
        assert ours == expected, (h, secret)
