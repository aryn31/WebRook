import random
from email.utils import parsedate_to_datetime
from datetime import UTC, datetime

from app.config import get_settings

RETRYABLE_STATUS = {408, 429}


def is_retryable_status(status: int) -> bool:
    return status in RETRYABLE_STATUS or 500 <= status <= 599


def retry_delay_seconds(attempt_number: int, retry_after: str | None = None) -> float:
    """Delay before the next attempt, after ``attempt_number`` attempts have failed.

    Exponential (x4 per attempt: ~30s, 2m, 8m, 32m) with +/-25% jitter so many failing deliveries
    don't all retry at the same instant. A larger Retry-After from the destination is honoured, up to the cap.
    """
    s = get_settings()
    base = s.retry_base_delay_seconds * (4 ** max(attempt_number - 1, 0))
    delay = min(base, s.retry_max_delay_seconds) * random.uniform(0.75, 1.25)
    hinted = _parse_retry_after(retry_after)
    if hinted is not None:
        delay = max(delay, min(hinted, s.retry_max_delay_seconds))
    return delay


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max((when - datetime.now(UTC)).total_seconds(), 0.0)
