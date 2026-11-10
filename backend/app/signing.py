"""Request signing. Every request carries two signatures over the same timestamp and body:

- HookFlow's own: ``HookFlow-Signature: v1=<hex>``, HMAC-SHA256 of ``{timestamp}.{body}`` keyed with the whole
  secret string (see docs/signatures.md).
- Standard Webhooks (https://www.standardwebhooks.com): ``webhook-signature: v1,<base64>``, HMAC-SHA256 of
  ``{webhook-id}.{timestamp}.{body}`` keyed with the base64-decoded part of the secret after ``whsec_``. Receivers
  can verify it with the official libraries.

Secrets made since Standard Webhooks support are ``whsec_`` + standard base64 of 24 random bytes, which works with
every library. Older secrets (base64url) still work with HookFlow's own scheme, but Standard Webhooks libraries
may not accept them; rotating the secret gives a new-format one.
"""

import base64
import binascii
import hashlib
import hmac

PREFIX = "whsec_"


def sign(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"v1={mac.hexdigest()}"


def verify(secret: str, timestamp: int, body: bytes, header: str) -> bool:
    expected = sign(secret, timestamp, body)
    return any(hmac.compare_digest(expected, part.strip()) for part in header.split(","))


def _encoded(secret: str) -> str:
    return secret[len(PREFIX):] if secret.startswith(PREFIX) else secret


def standard_key(secret: str) -> bytes:
    """The HMAC key Standard Webhooks libraries derive from a secret (same lenient decoding as the official one)."""
    encoded = _encoded(secret)
    try:
        return base64.b64decode(encoded + "==")
    except (binascii.Error, ValueError):
        return encoded.encode()


def is_standard_secret(secret: str) -> bool:
    """True if every Standard Webhooks library, including strict ones, can use this secret."""
    encoded = _encoded(secret)
    try:
        return secret.startswith(PREFIX) and len(base64.b64decode(encoded, validate=True)) >= 24
    except (binascii.Error, ValueError):
        return False


def sign_standard(secret: str, msg_id: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(standard_key(secret), f"{msg_id}.{timestamp}.".encode() + body, hashlib.sha256)
    return "v1," + base64.b64encode(mac.digest()).decode()


def signature_headers(secrets: list[str], msg_id: str, timestamp: int, body: bytes) -> dict[str, str]:
    """All signature headers for a request. During a secret rotation both secrets sign."""
    return {
        "HookFlow-Timestamp": str(timestamp),
        "HookFlow-Signature": ",".join(sign(s, timestamp, body) for s in secrets),
        "webhook-id": msg_id,
        "webhook-timestamp": str(timestamp),
        "webhook-signature": " ".join(sign_standard(s, msg_id, timestamp, body) for s in secrets),
    }
