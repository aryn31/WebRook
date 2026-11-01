"""Per-endpoint concurrency limit, shared by all workers.

Each endpoint has a Redis sorted set of the deliveries currently being sent to it, scored by when their slot
expires. A slot expires on its own after the delivery lease, so a crashed worker can't hold one forever.

If Redis is unreachable the limit is skipped (fail open): delivery matters more than the limit.
"""

import logging
import time

import redis

from app.ratelimit import get_redis

log = logging.getLogger("hookflow.worker")

_ACQUIRE = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
if redis.call('ZSCORE', KEYS[1], ARGV[3]) or redis.call('ZCARD', KEYS[1]) < tonumber(ARGV[4]) then
  redis.call('ZADD', KEYS[1], ARGV[2], ARGV[3])
  redis.call('EXPIRE', KEYS[1], ARGV[5])
  return 1
end
return 0
"""


def _key(endpoint_id: str) -> str:
    return f"conc:{endpoint_id}"


def acquire(endpoint_id: str, delivery_id: str, limit: int, ttl_seconds: int) -> bool:
    if limit <= 0:
        return True
    now = time.time()
    try:
        got = get_redis().eval(_ACQUIRE, 1, _key(endpoint_id), now, now + ttl_seconds, delivery_id, limit,
                               ttl_seconds + 1)
    except redis.RedisError:
        log.warning("Concurrency limiter unavailable; sending anyway", extra={"endpoint_id": endpoint_id})
        return True
    return bool(got)


def release(endpoint_id: str, delivery_id: str) -> None:
    try:
        get_redis().zrem(_key(endpoint_id), delivery_id)
    except redis.RedisError:
        pass  # the slot expires on its own


def in_flight(endpoint_id: str) -> int:
    try:
        return int(get_redis().zcount(_key(endpoint_id), time.time(), "+inf"))
    except redis.RedisError:
        return 0
