"""Receiver security check: does an endpoint really verify HookFlow signatures?

Sends the endpoint five test requests at once:

- ``valid``: correctly signed, current timestamp. Should be accepted (2xx).
- ``wrong_signature``: signed with a random secret. Should be rejected.
- ``tampered_body``: signed, then the body changed. Should be rejected.
- ``old_timestamp``: correctly signed, but an hour old (a replayed request). Should be rejected.
- ``missing_signature``: no signature header at all. Should be rejected.

Any non-2xx answer counts as rejected. A 4xx is ideal; a 5xx is reported because it makes senders retry.
Requests go through the same guarded sender as real deliveries, so private addresses stay blocked.
"""

import json
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from app.signing import sign
from app.worker.engine import Outcome, send

EVENT_TYPE = "hookflow.security_check"
OLD_SECONDS = 3600

PROBES = [
    ("valid", "Correctly signed request", True),
    ("wrong_signature", "Signed with the wrong secret", False),
    ("tampered_body", "Body changed after signing", False),
    ("old_timestamp", "Correct signature, but an hour old", False),
    ("missing_signature", "No signature header", False),
]
LABEL = {name: label for name, label, _ in PROBES}
SHOULD_ACCEPT = {name: accept for name, _, accept in PROBES}


def _body(probe: str, now: datetime) -> bytes:
    return json.dumps(
        {
            "id": f"evt_securitycheck_{secrets.token_hex(6)}",
            "type": EVENT_TYPE,
            "created_at": now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "data": {
                "probe": probe,
                "note": "Security check from HookFlow. Only the correctly signed request should be accepted.",
            },
        },
        separators=(",", ":"),
    ).encode()


def _request(probe: str, endpoint_id: str, signing_secrets: list[str]) -> tuple[bytes, dict[str, str]]:
    now = datetime.now(UTC)
    ts = int(time.time()) - (OLD_SECONDS if probe == "old_timestamp" else 0)
    body = _body(probe, now)
    if probe == "wrong_signature":
        signature = sign("whsec_" + secrets.token_urlsafe(24), ts, body)
    else:
        signature = ",".join(sign(s, ts, body) for s in signing_secrets)
    if probe == "tampered_body":
        body = body.replace(b'"probe":"tampered_body"', b'"probe":"tampered_body","total":1')
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "HookFlow/1.0 (security check)",
        "HookFlow-Event-Id": f"evt_securitycheck_{probe}",
        "HookFlow-Event-Type": EVENT_TYPE,
        "HookFlow-Delivery-Id": f"dlv_securitycheck_{endpoint_id}",
        "HookFlow-Attempt": "1",
        "HookFlow-Timestamp": str(ts),
        "HookFlow-Security-Check": probe,
    }
    if probe != "missing_signature":
        headers["HookFlow-Signature"] = signature
    return body, headers


def _verdict(results: dict[str, Outcome]) -> tuple[str, str]:
    """(verdict, summary). Verdicts: pass, fail, partial, inconclusive."""
    valid = results["valid"]
    if not valid.success:
        reason = valid.error or "it didn't answer with a 2xx"
        return "inconclusive", (f"Your endpoint didn't accept the correctly signed request ({reason}), so we can't tell "
                                "whether it checks signatures. Make sure it's up and answers 2xx to valid requests, "
                                "including event type hookflow.security_check, then run the check again.")
    unanswered = [LABEL[p] for p, o in results.items() if not o.success and o.status_code is None]
    if unanswered:
        return "inconclusive", ("Some test requests got no answer (" + ", ".join(unanswered).lower() + "), so the result "
                                "isn't reliable. Run the check again.")
    accepted = [p for p in ("wrong_signature", "tampered_body", "missing_signature") if results[p].success]
    if accepted:
        return "fail", ("Your endpoint accepted requests that weren't signed by HookFlow, so anyone who finds its URL "
                        "can send it fake events. Verify the HookFlow-Signature header before trusting a request.")
    if results["old_timestamp"].success:
        return "partial", ("Your endpoint checks signatures, but it accepted an hour-old request. Someone who captures a "
                           "real request could send it again later. Also reject requests whose HookFlow-Timestamp is "
                           "more than 5 minutes from now.")
    return "pass", "Your endpoint accepted the genuine request and rejected every forged one."


def run(endpoint_id: str, url: str, signing_secrets: list[str]) -> dict:
    """Send the five test requests and return the result to store and show."""
    requests = {name: _request(name, endpoint_id, signing_secrets) for name, _, _ in PROBES}
    with ThreadPoolExecutor(max_workers=len(PROBES)) as pool:
        futures = {name: pool.submit(send, url, body, headers) for name, (body, headers) in requests.items()}
        results = {name: f.result() for name, f in futures.items()}

    verdict, summary = _verdict(results)
    probes = []
    for name, _, should_accept in PROBES:
        o = results[name]
        accepted = o.success
        probes.append({
            "name": name,
            "label": LABEL[name],
            "expected": "accept" if should_accept else "reject",
            "status_code": o.status_code,
            "error": None if o.status_code is not None else o.error,
            "accepted": accepted,
            "ok": accepted == should_accept and (accepted or o.status_code is not None),
            # Rejected, but with a server error: senders treat 5xx as "try again".
            "server_error": (not accepted) and o.status_code is not None and o.status_code >= 500,
        })
    return {"verdict": verdict, "summary": summary, "checked_at": datetime.now(UTC).isoformat(), "probes": probes}
