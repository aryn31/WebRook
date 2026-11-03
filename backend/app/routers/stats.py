from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter
from sqlalchemy import case, func, literal, select

from app.deps import DB, EventsRead
from app.models import Delivery, DeliveryAttempt, DeliveryStatus, Event
from app.schemas import StatsOut

router = APIRouter(prefix="/v1/stats", tags=["stats"])

_RANGES = {"24h": (timedelta(hours=24), "hour"), "7d": (timedelta(days=7), "day"), "30d": (timedelta(days=30), "day")}


@router.get("", response_model=StatsOut)
def stats(principal: EventsRead, db: DB, range: Literal["24h", "7d", "30d"] = "7d") -> dict:  # noqa: A002
    span, unit = _RANGES[range]
    now = datetime.now(UTC)
    start = now - span
    uid = principal.user.id

    events_total = db.scalar(select(func.count()).where(Event.user_id == uid, Event.created_at >= start)) or 0
    by_status = {s.value: 0 for s in DeliveryStatus}
    for status, n in db.execute(
        select(Delivery.status, func.count())
        .where(Delivery.user_id == uid, Delivery.created_at >= start)
        .group_by(Delivery.status)
    ):
        by_status[status] = n

    # Time series, bucketed in UTC.
    ev_bucket = func.date_trunc(unit, func.timezone("UTC", Event.created_at)).label("b")
    dl_bucket = func.date_trunc(unit, func.timezone("UTC", Delivery.created_at)).label("b")
    series: dict[datetime, dict[str, int]] = {}

    def _bucket_start(dt: datetime) -> datetime:
        dt = dt.replace(minute=0, second=0, microsecond=0)
        return dt.replace(hour=0) if unit == "day" else dt

    cursor = _bucket_start(start)
    step = timedelta(hours=1) if unit == "hour" else timedelta(days=1)
    while cursor <= now:
        series[cursor] = {"events": 0, "delivered": 0, "failed": 0}
        cursor += step

    for b, n in db.execute(
        select(ev_bucket, func.count()).where(Event.user_id == uid, Event.created_at >= start).group_by(ev_bucket)
    ):
        series.setdefault(b.replace(tzinfo=UTC), {"events": 0, "delivered": 0, "failed": 0})["events"] = n

    for b, delivered, failed in db.execute(
        select(
            dl_bucket,
            func.sum(case((Delivery.status == DeliveryStatus.DELIVERED, 1), else_=literal(0))),
            func.sum(case((Delivery.status == DeliveryStatus.FAILED, 1), else_=literal(0))),
        )
        .where(Delivery.user_id == uid, Delivery.created_at >= start)
        .group_by(dl_bucket)
    ):
        row = series.setdefault(b.replace(tzinfo=UTC), {"events": 0, "delivered": 0, "failed": 0})
        row["delivered"], row["failed"] = int(delivered or 0), int(failed or 0)

    p50, p95 = db.execute(
        select(
            func.percentile_cont(0.5).within_group(DeliveryAttempt.duration_ms),
            func.percentile_cont(0.95).within_group(DeliveryAttempt.duration_ms),
        )
        .join(Delivery, Delivery.id == DeliveryAttempt.delivery_id)
        .where(Delivery.user_id == uid, DeliveryAttempt.completed_at >= start, DeliveryAttempt.duration_ms.is_not(None))
    ).one()

    return {
        "range": range,
        "latency_ms": {"p50": p50, "p95": p95} if p50 is not None else None,
        "events_total": events_total,
        "deliveries_total": sum(by_status.values()),
        "deliveries_by_status": by_status,
        "series": [{"bucket": k, **v} for k, v in sorted(series.items())],
    }
