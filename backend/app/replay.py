"""Manual replay of failed or cancelled deliveries.

A replay resets the *same* delivery (same event ID, same delivery ID) to ``pending`` with a fresh retry
budget. Earlier attempts are kept; new attempts continue the numbering. Each replay is recorded in
``delivery_replays`` and the audit log.

Storm protection:
- Only deliveries in a final failed/cancelled state can be replayed, so repeated replay requests for the
  same delivery can't stack up: once replayed it's pending again and further requests get a 409.
- Replays are rate limited per account (each delivery replayed counts once).
- The endpoint's current state applies: it must be enabled, and its URL must pass the current URL rules.
  Send-time destination checks (SSRF) run again on every attempt.
"""

from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from app import audit, ratelimit
from app.config import get_settings
from app.deps import Principal
from app.ids import new_id
from app.models import Delivery, DeliveryReplay, DeliveryStatus
from app.schemas import Actor, ReplayOut
from app.urlguard import validate_url_format

REPLAYABLE = (DeliveryStatus.FAILED, DeliveryStatus.CANCELLED)


def why_not_replayable(d: Delivery) -> str | None:
    """None if the delivery can be replayed now, otherwise a user-facing reason."""
    if d.status not in REPLAYABLE:
        return f"Only failed or cancelled deliveries can be replayed; this one is {d.status}."
    if d.endpoint.archived_at is not None:
        return "The endpoint has been deleted."
    if not d.endpoint.enabled:
        return "The endpoint is disabled. Enable it, then replay."
    try:
        validate_url_format(d.endpoint.url)
    except ValueError as exc:
        return f"The endpoint URL is no longer allowed: {exc}"
    return None


def enforce_rate_limit(user_id: str, count: int) -> None:
    ratelimit.enforce(f"replay:{user_id}", get_settings().replay_rate_limit_per_minute, cost=count)


def replay(db: Session, principal: Principal, d: Delivery) -> DeliveryReplay | None:
    """Reset ``d`` for redelivery in the caller's transaction. Returns None if it changed state meanwhile.

    The caller checks ``why_not_replayable`` and the rate limit first, stages the outbox message, and commits.
    """
    now = datetime.now(UTC)
    result = db.execute(
        update(Delivery)
        .where(Delivery.id == d.id, Delivery.status == d.status)  # only if nobody changed it since we read it
        .values(
            status=DeliveryStatus.PENDING,
            next_attempt_at=now,
            max_attempts=Delivery.attempt_count + d.endpoint.max_attempts,
            retry_base_attempt=Delivery.attempt_count,
            replay_count=Delivery.replay_count + 1,
            last_replayed_at=now,
            enqueued_at=None,
            locked_until=None,
            last_error=None,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        return None
    r = DeliveryReplay(
        id=new_id("rpl"),
        delivery_id=d.id,
        user_id=principal.user.id,
        actor_type=principal.via,
        api_key_id=principal.api_key.id if principal.api_key else None,
        previous_status=d.status,
        first_attempt_number=d.attempt_count + 1,
        created_at=now,
    )
    db.add(r)
    audit.record(
        db, principal, "delivery.replayed", "delivery", d.id,
        {"replay_id": r.id, "event_id": d.event_id, "endpoint_id": d.endpoint_id, "previous_status": d.status},
    )
    return r


def replay_out(r: DeliveryReplay) -> ReplayOut:
    return ReplayOut(
        id=r.id,
        delivery_id=r.delivery_id,
        previous_status=r.previous_status,
        first_attempt_number=r.first_attempt_number,
        requested_by=Actor(type=r.actor_type, api_key_id=r.api_key_id),
        created_at=r.created_at,
    )
