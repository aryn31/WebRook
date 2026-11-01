from app import ops, outbox
from app.db import SessionLocal
from app.worker.celery_app import celery_app
from app.worker.engine import process_delivery, sweep


@celery_app.task(name="hookflow.deliver")
def deliver(delivery_id: str) -> str:
    return process_delivery(delivery_id)


@celery_app.task(name="hookflow.publish_outbox")
def publish_outbox_task() -> int:
    ops.beat_heartbeat()
    return outbox.publish_due()


@celery_app.task(name="hookflow.sweep")
def sweep_task() -> dict[str, int]:
    ops.beat_heartbeat()
    return sweep()


@celery_app.task(name="hookflow.monitor")
def monitor_task() -> list[str]:
    """Log an alert if delivery work is stuck (see app/ops.py)."""
    with SessionLocal() as db:
        return ops.check_alerts(ops.snapshot(db))
