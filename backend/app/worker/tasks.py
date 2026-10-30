from app.worker.celery_app import celery_app
from app.worker.engine import process_delivery, sweep


@celery_app.task(name="hookflow.deliver")
def deliver(delivery_id: str) -> str:
    return process_delivery(delivery_id)


@celery_app.task(name="hookflow.sweep")
def sweep_task() -> dict[str, int]:
    return sweep(enqueue=lambda delivery_id: deliver.delay(delivery_id))
