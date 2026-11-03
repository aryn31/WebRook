"""Verify webhook requests sent by HookFlow.

HookFlow signs every request with HMAC-SHA256::

    HookFlow-Timestamp: 1793361600
    HookFlow-Signature: v1=<hex hmac_sha256(secret, "{timestamp}." + raw_body)>

During a signing-secret rotation grace period the signature header carries two values,
``v1=<new>,v1=<old>``; a request is valid if any one of them matches.

**Always pass the raw request body** (the exact bytes received). Parsing the JSON and serializing it again
changes the bytes and the signature will not match.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Iterable, Mapping, Tuple, Union

from .errors import WebhookVerificationError

DEFAULT_TOLERANCE_SECONDS = 300

HEADER_EVENT_ID = "HookFlow-Event-Id"
HEADER_EVENT_TYPE = "HookFlow-Event-Type"
HEADER_DELIVERY_ID = "HookFlow-Delivery-Id"
HEADER_ATTEMPT = "HookFlow-Attempt"
HEADER_TIMESTAMP = "HookFlow-Timestamp"
HEADER_SIGNATURE = "HookFlow-Signature"

Headers = Union[Mapping[str, Any], Iterable[Tuple[str, Any]]]

__all__ = [
    "DEFAULT_TOLERANCE_SECONDS",
    "WebhookVerificationError",
    "compute_signature",
    "sign",
    "verify",
    "verify_signature",
]


def _to_bytes(payload: bytes | bytearray | memoryview | str) -> bytes:
    if isinstance(payload, (bytes, bytearray, memoryview)):
        return bytes(payload)
    if isinstance(payload, str):
        return payload.encode("utf-8")
    raise TypeError(
        "payload must be the raw request body as bytes or str, not "
        f"{type(payload).__name__}. Do not parse and re-serialize the JSON: use e.g. "
        "`await request.body()` (FastAPI/Starlette) or `request.get_data()` (Flask)."
    )


def _header_lookup(headers: Headers) -> dict[str, str]:
    items = headers.items() if hasattr(headers, "items") else headers
    out: dict[str, str] = {}
    for key, value in items:  # type: ignore[union-attr]
        if isinstance(key, bytes):
            key = key.decode("latin-1")
        if isinstance(value, bytes):
            value = value.decode("latin-1")
        elif isinstance(value, (list, tuple)):  # e.g. multi-value header dicts
            value = ",".join(str(v) for v in value)
        out.setdefault(str(key).lower(), str(value))
    return out


def compute_signature(secret: str, timestamp: int | str, payload: bytes | str) -> str:
    """Return the hex HMAC-SHA256 of ``"{timestamp}." + payload`` keyed with ``secret`` (no ``v1=`` prefix)."""
    key = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    return hmac.new(key, f"{timestamp}.".encode() + _to_bytes(payload), hashlib.sha256).hexdigest()


def sign(secret: str, timestamp: int | str, payload: bytes | str) -> str:
    """Return a ``HookFlow-Signature`` value (``v1=<hex>``). Useful for testing your receiver."""
    return "v1=" + compute_signature(secret, timestamp, payload)


def _check(
    payload: bytes,
    headers: Headers,
    secret: str,
    tolerance_seconds: float | None,
    now: float | None,
) -> None:
    if not secret:
        raise ValueError("secret must be your endpoint's signing secret (whsec_...).")
    lookup = _header_lookup(headers)
    timestamp = lookup.get(HEADER_TIMESTAMP.lower())
    signature_header = lookup.get(HEADER_SIGNATURE.lower())
    if timestamp is None:
        raise WebhookVerificationError(f"Missing {HEADER_TIMESTAMP} header.", "missing_header")
    if signature_header is None:
        raise WebhookVerificationError(f"Missing {HEADER_SIGNATURE} header.", "missing_header")

    timestamp = timestamp.strip()
    if not timestamp.isascii() or not timestamp.isdigit():
        raise WebhookVerificationError(f"{HEADER_TIMESTAMP} is not a Unix timestamp.", "invalid_timestamp")
    if tolerance_seconds is not None:
        current = time.time() if now is None else now
        if abs(current - int(timestamp)) > tolerance_seconds:
            raise WebhookVerificationError(
                f"{HEADER_TIMESTAMP} is more than {tolerance_seconds:g} seconds from the current time.",
                "timestamp_out_of_tolerance",
            )

    candidates = []
    for part in signature_header.split(","):
        part = part.strip()
        if part.startswith("v1="):
            candidates.append(part[3:].encode("ascii", errors="replace"))
    if not candidates:
        raise WebhookVerificationError(f"{HEADER_SIGNATURE} has no v1= signature.", "no_signatures")

    expected = compute_signature(secret, timestamp, payload).encode("ascii")
    # Check every candidate (no early exit) with a constant-time comparison.
    matched = False
    for candidate in candidates:
        matched |= hmac.compare_digest(expected, candidate)
    if not matched:
        raise WebhookVerificationError(
            "No signature matches. Check the signing secret, and make sure you pass the raw request body.",
            "signature_mismatch",
        )


def verify_signature(
    payload: bytes | str,
    headers: Headers,
    secret: str,
    tolerance_seconds: float | None = DEFAULT_TOLERANCE_SECONDS,
    *,
    now: float | None = None,
) -> None:
    """Like :func:`verify` but does not parse the body. Raises :class:`WebhookVerificationError`."""
    _check(_to_bytes(payload), headers, secret, tolerance_seconds, now)


def verify(
    payload: bytes | str,
    headers: Headers,
    secret: str,
    tolerance_seconds: float | None = DEFAULT_TOLERANCE_SECONDS,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Verify a HookFlow webhook request and return the parsed event.

    :param payload: the **raw** request body, exactly as received (``bytes``, or ``str`` decoded as UTF-8).
    :param headers: the request headers; any mapping or list of ``(name, value)`` pairs. Lookup is
        case-insensitive.
    :param secret: the endpoint's full signing secret, including the ``whsec_`` prefix.
    :param tolerance_seconds: reject requests whose ``HookFlow-Timestamp`` is further than this from now
        (default 300). ``None`` disables the check (not recommended).
    :param now: override the current Unix time (for tests).
    :returns: the event, ``{"id", "type", "created_at", "data"}``.
    :raises WebhookVerificationError: missing headers, malformed or stale timestamp, or no matching signature.
    """
    raw = _to_bytes(payload)
    _check(raw, headers, secret, tolerance_seconds, now)
    try:
        event = json.loads(raw)
    except ValueError:
        raise WebhookVerificationError("Payload is not valid JSON.", "invalid_payload") from None
    if not isinstance(event, dict):
        raise WebhookVerificationError("Payload is not a JSON object.", "invalid_payload")
    return event
