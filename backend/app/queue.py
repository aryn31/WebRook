import logging
from functools import lru_cache

from celery import Celery

from app.config import get_settings

log = logging.getLogger("hookflow.queue")


@lru_cache
def _producer() -> Celery:
    # A lightweight Celery client; the worker defines the tasks. Short timeouts so a Redis outage
    # never stalls an API request for long.
    app = Celery("hookflow-producer", broker=get_settings().redis_url)
    app.conf.broker_transport_options = {"socket_connect_timeout": 2, "socket_timeout": 2}
    return app


def send_delivery(delivery_id: str) -> None:
    """Publish one "deliver X" message. Raises if the broker is unreachable.

    Called only by the outbox (app/outbox.py), never directly.
    """
    _producer().send_task("hookflow.deliver", args=[delivery_id], retry=False)
