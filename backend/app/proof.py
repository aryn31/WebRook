"""Proof-of-delivery pages and their signed receipts.

A proof link is a public page about one delivery: when it was sent, every attempt and what the receiver answered,
and the SHA-256 of the exact body sent. The page is read live from the database each time it's opened.

Each view also comes with a receipt: the same facts as a JSON string, signed with Ed25519. Anyone can check a saved
receipt offline against the public key at GET /v1/proof/public-key, so a receipt can't be edited without it
showing. The key is derived from SECRET_ENCRYPTION_KEY, so changing that setting changes the key (receipts signed
with the old key no longer verify against the new one).
"""

import base64
import hashlib
import json
import secrets
from datetime import datetime
from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.config import get_settings

TOKEN_PREFIX = "pod_"


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(24)


def proof_url(token: str) -> str:
    return f"{get_settings().app_url.rstrip('/')}/proof/{token}"


@lru_cache(maxsize=4)
def _private_key(secret: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b"hookflow-proof:" + secret.encode()).digest())


def _key() -> Ed25519PrivateKey:
    return _private_key(get_settings().secret_encryption_key)


def public_key() -> tuple[str, str]:
    """(key_id, base64 raw public key)."""
    raw = _key().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:16], base64.b64encode(raw).decode()


def sign_receipt(facts: dict) -> dict:
    payload = json.dumps(facts, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_iso)
    signature = base64.b64encode(_key().sign(payload.encode())).decode()
    return {"payload": payload, "signature": signature, "algorithm": "Ed25519", "key_id": public_key()[0]}


def _iso(value):
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    raise TypeError(f"Can't put {type(value).__name__} in a receipt")


def public_url(url: str) -> str:
    """The endpoint URL without credentials or query string, which can hold secrets."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"  # IPv6
    if parts.port:
        host = f"{host}:{parts.port}"
    shown = urlunsplit((parts.scheme, host, parts.path, "", ""))
    return shown + ("?…" if parts.query else "")
