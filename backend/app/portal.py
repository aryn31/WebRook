"""Customer portal links.

A portal token lets one consumer manage their own endpoints for a limited time. It is signed, not stored:
``hfp_<payload>.<signature>``, where the payload is base64url JSON with the account, the consumer, an expiry and
an optional brand name, and the signature is an HMAC of the payload keyed from SECRET_ENCRYPTION_KEY.

The token goes in the URL fragment (``/portal#token=…``), which browsers don't send to servers or in Referer
headers. The portal page then sends it as ``Authorization: Bearer hfp_…`` to the /v1/portal routes.
"""

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.config import get_settings

PREFIX = "hfp_"


def _key() -> bytes:
    return hashlib.sha256(b"hookflow-portal:" + get_settings().secret_encryption_key.encode()).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass
class PortalClaims:
    account_id: str
    consumer_id: str
    expires_at: datetime
    brand_name: str | None


def create_token(account_id: str, consumer_id: str, ttl: timedelta, brand_name: str | None = None) -> tuple[str, datetime]:
    expires = int(time.time() + ttl.total_seconds())
    payload = _b64(json.dumps({"a": account_id, "c": consumer_id, "e": expires, "b": brand_name},
                              separators=(",", ":")).encode())
    sig = _b64(hmac.new(_key(), payload.encode(), hashlib.sha256).digest())
    return f"{PREFIX}{payload}.{sig}", datetime.fromtimestamp(expires, UTC)


def read_token(token: str) -> PortalClaims | None:
    """The token's claims, or None if it's malformed, forged or expired."""
    if not token.startswith(PREFIX) or token.count(".") != 1:
        return None
    payload, sig = token[len(PREFIX):].split(".")
    expected = _b64(hmac.new(_key(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        data = json.loads(_unb64(payload))
        expires = int(data["e"])
        account_id, consumer_id = str(data["a"]), str(data["c"])
    except (ValueError, KeyError, TypeError):
        return None
    if expires <= time.time():
        return None
    return PortalClaims(account_id, consumer_id, datetime.fromtimestamp(expires, UTC), data.get("b"))


def portal_url(token: str) -> str:
    return f"{get_settings().app_url.rstrip('/')}/portal#token={token}"
