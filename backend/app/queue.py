import logging
from functools import lru_cache

from celery import Celery

from app.config import get_settings

log = logging.getLogger("hookflow.queue")


@lru_cache
def _producer() -> Celery:
    # A lightweight Celery client for the API process; the worker defines the tasks.
    app = Celery("hookflow-api", broker=get_settings().redis_url)
    app.conf.broker_transport_options = {"socket_connect_timeout": 2, "socket_timeout": 2}
    return app


def enqueue_delivery(delivery_id: str) -> bool:
    """Best-effort queue publish. Returns False if the broker is unreachable."""
    try:
        _producer().send_task("hookflow.deliver", args=[delivery_id], retry=False)
        return True
    except Exception:
        log.warning("Could not queue delivery; the sweeper will pick it up", extra={"delivery_id": delivery_id})
        return False
