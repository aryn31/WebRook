import time
from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import func, select

from app import ratelimit
from app.deps import DB, EventsRead
from app.models import Event
from app.routers.events import DAY, _limits
from app.schemas import UsageOut

router = APIRouter(prefix="/v1/usage", tags=["usage"])


def _window(limit: int, used: int, seconds: int) -> dict:
    now = time.time()
    unlimited = limit <= 0
    return {
        "limit": None if unlimited else limit,
        "used": used,
        "remaining": None if unlimited else max(limit - used, 0),
        "resets_in_seconds": max(int(seconds - now % seconds), 1),
    }


@router.get("", response_model=UsageOut)
def usage(principal: EventsRead, db: DB) -> dict:
    """Where the account stands against its ingestion limits. Reading this doesn't count toward them."""
    user = principal.user
    rate_limit, quota = _limits(user)
    # Count today's events from the database: always accurate, even for days the account was unlimited (when the
    # quota counter isn't kept). It matches the counter the quota is enforced with.
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    today = db.scalar(select(func.count()).where(Event.user_id == user.id, Event.created_at >= midnight)) or 0
    this_minute = ratelimit.peek(f"events:{user.id}", 60) or 0
    return {
        "events_today": _window(quota, today, DAY),
        "requests_this_minute": _window(rate_limit, this_minute, 60),
    }
