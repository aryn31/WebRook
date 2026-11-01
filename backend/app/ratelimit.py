import logging
import time
from dataclasses import dataclass
from functools import lru_cache

import redis

from app.config import get_settings
from app.errors import ApiError

log = logging.getLogger("hookflow.ratelimit")


@lru_cache
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, socket_timeout=1, socket_connect_timeout=1)


@dataclass
class Usage:
    limit: int
    used: int
    reset_seconds: int  # until the current window ends

    @property
    def remaining(self) -> int:
        return max(self.limit - self.used, 0)

    @property
    def exceeded(self) -> bool:
        return self.used > self.limit


def hit(bucket: str, limit: int, window_seconds: int = 60, cost: int = 1) -> Usage | None:
    """Count ``cost`` units against a fixed window. Returns None if Redis is unreachable (fail open)."""
    now = time.time()
    window = int(now // window_seconds)
    key = f"rl:{bucket}:{window}"
    try:
        pipe = get_redis().pipeline()
        pipe.incrby(key, cost)
        pipe.expire(key, window_seconds + 1)
        used = int(pipe.execute()[0])
    except redis.RedisError:
        log.warning("Rate limiter unavailable; allowing request", extra={"bucket": bucket.split(":")[0]})
        return None
    reset = max(int(window_seconds - now % window_seconds), 1)
    return Usage(limit=limit, used=used, reset_seconds=reset)


def peek(bucket: str, window_seconds: int) -> int | None:
    """Units used so far in the current window, without counting anything. None if Redis is unreachable."""
    key = f"rl:{bucket}:{int(time.time() // window_seconds)}"
    try:
        value = get_redis().get(key)
    except redis.RedisError:
        return None
    return int(value) if value else 0


def give_back(bucket: str, window_seconds: int, cost: int = 1) -> None:
    """Undo a hit that turned out not to count (e.g. a request that was rejected later)."""
    key = f"rl:{bucket}:{int(time.time() // window_seconds)}"
    try:
        get_redis().decrby(key, cost)
    except redis.RedisError:
        pass


def enforce(bucket: str, limit: int, window_seconds: int = 60, cost: int = 1) -> Usage | None:
    """Fixed-window limiter. Raises 429 when ``bucket`` exceeds ``limit`` per window.

    ``cost`` lets one request use up several units (e.g. replaying 10 deliveries at once costs 10).

    Fails open if Redis is unreachable: a Redis outage should not lock everyone out of login.
    """
    usage = hit(bucket, limit, window_seconds, cost)
    if usage is not None and usage.exceeded:
        raise ApiError(
            429,
            f"Too many requests. Try again in {usage.reset_seconds} seconds.",
            headers={"Retry-After": str(usage.reset_seconds)},
        )
    return usage
