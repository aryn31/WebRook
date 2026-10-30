import logging
import time
from functools import lru_cache

import redis

from app.config import get_settings
from app.errors import ApiError

log = logging.getLogger("hookflow.ratelimit")


@lru_cache
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, socket_timeout=1, socket_connect_timeout=1)


def enforce(bucket: str, limit: int, window_seconds: int = 60) -> None:
    """Fixed-window limiter. Raises 429 when ``bucket`` exceeds ``limit`` per window.

    Fails open if Redis is unreachable: a Redis outage should not lock everyone out of login.
    """
    window = int(time.time() // window_seconds)
    key = f"rl:{bucket}:{window}"
    try:
        pipe = get_redis().pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds + 1)
        count = int(pipe.execute()[0])
    except redis.RedisError:
        log.warning("Rate limiter unavailable; allowing request", extra={"bucket": bucket.split(":")[0]})
        return
    if count > limit:
        retry_after = window_seconds - int(time.time() % window_seconds)
        raise ApiError(
            429,
            f"Too many requests. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )
