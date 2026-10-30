"""HMAC-SHA256 request signing. See docs/api.md#verifying-the-signature."""

import hashlib
import hmac


def sign(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"v1={mac.hexdigest()}"


def verify(secret: str, timestamp: int, body: bytes, header: str) -> bool:
    expected = sign(secret, timestamp, body)
    return any(hmac.compare_digest(expected, part.strip()) for part in header.split(","))
