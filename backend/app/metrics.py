"""Prometheus metrics at GET /metrics.

- Request counts and latency, measured in this API process.
- Pipeline state (queue depth, oldest waiting delivery, recent success rate and send latency, worker heartbeat),
  read from Postgres and Redis at scrape time, so the numbers cover every worker.
"""

import logging
import time

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, Histogram, generate_latest
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

from app import ops
from app.config import get_settings
from app.db import SessionLocal
from app.errors import ApiError
from app.security import constant_time_equals

log = logging.getLogger("hookflow.metrics")

HTTP_REQUESTS = Counter(
    "hookflow_http_requests_total", "API requests handled.", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "hookflow_http_request_duration_seconds", "API request latency.", ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)


async def track_requests(request: Request, call_next):
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        # Use the route template ("/v1/events/{event_id}") so IDs don't create a new series each.
        path = getattr(route, "path", "unmatched")
        if path != "/metrics":
            HTTP_REQUESTS.labels(request.method, path, str(status)).inc()
            HTTP_LATENCY.labels(request.method, path).observe(time.perf_counter() - start)


class PipelineCollector(Collector):
    def collect(self):
        up = GaugeMetricFamily("hookflow_pipeline_metrics_up", "1 if pipeline metrics could be read.")
        try:
            with SessionLocal() as db:
                snap = ops.snapshot(db)
        except Exception:
            log.warning("Could not read pipeline metrics", exc_info=True)
            up.add_metric([], 0)
            yield up
            return
        up.add_metric([], 1)
        yield up

        g = GaugeMetricFamily("hookflow_deliveries_queued", "Deliveries not yet finished, by status.",
                              labels=["status"])
        for status, n in snap.deliveries_by_status.items():
            g.add_metric([status], n)
        yield g
        yield GaugeMetricFamily("hookflow_delivery_oldest_due_seconds",
                                "How long the longest-waiting due delivery has waited.",
                                value=snap.oldest_due_seconds)
        yield GaugeMetricFamily("hookflow_outbox_unpublished", "Queue messages not yet published to Redis.",
                                value=snap.outbox_unpublished)
        yield GaugeMetricFamily("hookflow_outbox_oldest_due_seconds",
                                "How long the oldest due unpublished queue message has waited.",
                                value=snap.outbox_oldest_due_seconds)
        g = GaugeMetricFamily("hookflow_delivery_attempts_recent", "Delivery attempts in the last 5 minutes.",
                              labels=["result"])
        for result, n in snap.recent_attempts.items():
            g.add_metric([result], n)
        yield g
        g = GaugeMetricFamily("hookflow_delivery_latency_ms_recent",
                              "Time to send a delivery and get a response, last 5 minutes.", labels=["quantile"])
        for q, v in snap.recent_latency_ms.items():
            g.add_metric([q], v)
        yield g
        if snap.worker_silence_seconds is not None:
            yield GaugeMetricFamily("hookflow_worker_last_seen_seconds",
                                    "Seconds since the worker last ran a scheduled task.",
                                    value=snap.worker_silence_seconds)


REGISTRY.register(PipelineCollector())

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> Response:
    token = get_settings().metrics_token
    if token:
        scheme, _, given = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not constant_time_equals(given.strip(), token):
            raise ApiError(401, "Metrics require 'Authorization: Bearer <METRICS_TOKEN>'.")
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
