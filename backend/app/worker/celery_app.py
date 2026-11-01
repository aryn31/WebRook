from celery import Celery

from app.config import get_settings
from app.logconfig import configure_logging

configure_logging()
settings = get_settings()

celery_app = Celery("hookflow", broker=settings.redis_url, include=["app.worker.tasks"])
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
    worker_hijack_root_logger=False,
    beat_schedule={
        "publish-outbox": {
            "task": "hookflow.publish_outbox",
            "schedule": settings.outbox_poll_interval_seconds,
            "options": {"expires": max(settings.outbox_poll_interval_seconds, 1.0)},
        },
        "sweep-deliveries": {
            "task": "hookflow.sweep",
            "schedule": settings.sweep_interval_seconds,
            "options": {"expires": settings.sweep_interval_seconds},
        },
        "monitor": {
            "task": "hookflow.monitor",
            "schedule": 60.0,
            "options": {"expires": 60.0},
        },
    },
)
