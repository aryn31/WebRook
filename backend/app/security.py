import base64
import hashlib
import hmac
import secrets
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet

from app.config import get_settings

_hasher = PasswordHasher()
# Verified against when the email doesn't exist, so login takes the same time either way.
_DUMMY_HASH = _hasher.hash("hookflow-timing-equalizer")


# --- Passwords -------------------------------------------------------------

def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


# --- Opaque tokens (sessions, API keys) ------------------------------------
# These tokens are long and random, so a fast SHA-256 digest is a safe verifier.

def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def new_api_key() -> tuple[str, str, str]:
    """Return (full_key, prefix, key_hash). Format: ``hf_<8 hex>_<43 chars>``."""
    prefix = f"hf_{secrets.token_hex(4)}"
    key = f"{prefix}_{secrets.token_urlsafe(32)}"
    return key, prefix, sha256_hex(key)


def parse_api_key_prefix(key: str) -> str | None:
    parts = key.split("_")
    if len(parts) < 3 or parts[0] != "hf" or len(parts[1]) != 8:
        return None
    return f"hf_{parts[1]}"


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# --- Signing secrets (encrypted at rest) ------------------------------------

def new_signing_secret() -> str:
    # Standard Webhooks format: "whsec_" + standard base64 of random bytes (see app/signing.py).
    return "whsec_" + base64.b64encode(secrets.token_bytes(24)).decode()


@lru_cache
def _fernet() -> Fernet:
    return Fernet(get_settings().secret_encryption_key.encode())


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
