"""Prefixed, time-sortable IDs (ULID style), e.g. ``evt_01JBX7Q2...``.

Sorting IDs as strings sorts them by creation time, which keeps cursor pagination simple.
"""

import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        value, rem = divmod(value, 32)
        chars.append(_ALPHABET[rem])
    return "".join(reversed(chars))


def new_id(prefix: str) -> str:
    ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    return f"{prefix}_{_encode(ms, 10)}{_encode(rand, 16)}"
