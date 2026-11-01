"""Load test: send events to HookFlow as fast as possible, then wait for every delivery to finish.

Reports ingestion throughput and latency (p50/p95/p99), error counts by status, and how long the workers took to
deliver everything (read from GET /metrics).

Usage (from the repo root, with the Docker stack running):

    docker compose run --rm -v "$PWD/loadtest:/loadtest" api python /loadtest/ingest.py \
        --url http://api:8000 --key hf_live_... --requests 5000 --concurrency 50

The account's ingestion limits apply (600/minute and 10,000/day by default), so raise them for the test account:

    docker compose exec postgres psql -U hookflow -c \
        "UPDATE users SET event_rate_limit_per_minute = 0, daily_event_quota = 0 WHERE email = 'load@example.com'"

Never point this at production without limits in place: it creates real events and deliveries.
"""

import argparse
import asyncio
import statistics
import time
from collections import Counter

import httpx


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = (len(values) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


async def send_events(url: str, key: str, total: int, concurrency: int) -> tuple[list[float], Counter, float]:
    latencies: list[float] = []
    statuses: Counter = Counter()
    counter = iter(range(total))
    headers = {"Authorization": f"Bearer {key}"}

    async def worker(client: httpx.AsyncClient) -> None:
        for n in counter:
            body = {"event_type": "load.test", "data": {"n": n, "padding": "x" * 200}}
            t0 = time.perf_counter()
            try:
                r = await client.post("/v1/events", json=body, headers=headers)
                statuses[r.status_code] += 1
            except httpx.HTTPError as exc:
                statuses[type(exc).__name__] += 1
                continue
            latencies.append((time.perf_counter() - t0) * 1000)

    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=url, timeout=30, limits=limits) as client:
        start = time.perf_counter()
        await asyncio.gather(*(worker(client) for _ in range(concurrency)))
        elapsed = time.perf_counter() - start
    return latencies, statuses, elapsed


def queued(url: str, metrics_token: str | None) -> float | None:
    headers = {"Authorization": f"Bearer {metrics_token}"} if metrics_token else {}
    try:
        text = httpx.get(f"{url}/metrics", headers=headers, timeout=10).text
    except httpx.HTTPError:
        return None
    total = 0.0
    for line in text.splitlines():
        if line.startswith("hookflow_deliveries_queued{"):
            total += float(line.rsplit(" ", 1)[1])
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--key", required=True, help="API key for the test account")
    parser.add_argument("--requests", type=int, default=2000)
    parser.add_argument("--concurrency", type=int, default=25)
    parser.add_argument("--metrics-token", default=None)
    parser.add_argument("--drain-timeout", type=float, default=600, help="seconds to wait for deliveries")
    args = parser.parse_args()

    print(f"Sending {args.requests} events to {args.url} with {args.concurrency} concurrent clients...")
    latencies, statuses, elapsed = asyncio.run(send_events(args.url, args.key, args.requests, args.concurrency))
    accepted = statuses.get(202, 0)
    print("\nIngestion")
    print(f"  duration     {elapsed:.1f}s")
    print(f"  throughput   {len(latencies) / elapsed:.0f} requests/s ({accepted / elapsed:.0f} accepted/s)")
    print(f"  latency ms   p50 {percentile(latencies, 0.5):.0f}  p95 {percentile(latencies, 0.95):.0f}  "
          f"p99 {percentile(latencies, 0.99):.0f}  max {max(latencies, default=0):.0f}  "
          f"mean {statistics.fmean(latencies) if latencies else 0:.0f}")
    print(f"  responses    {dict(statuses)}")

    print("\nDelivery (waiting for the queue to drain)")
    start = time.perf_counter()
    while True:
        left = queued(args.url, args.metrics_token)
        if left is None:
            print("  /metrics unavailable; skipping")
            return
        if left == 0:
            break
        if time.perf_counter() - start > args.drain_timeout:
            print(f"  gave up after {args.drain_timeout:.0f}s with {left:.0f} deliveries still queued")
            return
        time.sleep(1)
    drained = time.perf_counter() - start
    print(f"  queue empty {drained:.1f}s after ingestion finished "
          f"({elapsed + drained:.1f}s from the first event)")


if __name__ == "__main__":
    main()
