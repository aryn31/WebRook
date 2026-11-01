# Running HookFlow

How to configure, monitor and size a HookFlow deployment. For the API itself, see [api.md](api.md).

## Processes

| Process | Command | How many |
| --- | --- | --- |
| API | `uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers` | 1 or more |
| Worker | `celery -A app.worker.celery_app worker --loglevel=INFO --concurrency=8` | 1 or more |
| Scheduler (beat) | `celery -A app.worker.celery_app beat --loglevel=INFO --schedule=/tmp/celerybeat-schedule` | **exactly 1** |
| Migrations | `alembic upgrade head` | before each deploy |

The scheduler runs the outbox publisher (every second), the sweeper (every 5 seconds: lease recovery, lost-message
recovery, cleanup and retention) and the monitor (every minute: alerts).

**One container for everything.** `backend/start.sh` runs migrations, then the worker with the scheduler built in
(`worker -B`) and the API, for hosts where only one service is affordable (such as Render's free plan). If the worker
or the API stops, the script exits so the host restarts the container. Run exactly one copy, because it includes the
scheduler.

## Settings

All settings are environment variables. Only `SECRET_ENCRYPTION_KEY` is required.

| Variable | Default | What it does |
| --- | --- | --- |
| `DATABASE_URL` | local Postgres | `postgres://`, `postgresql://` and `postgresql+psycopg://` all work |
| `REDIS_URL` | local Redis | Queue and rate-limit counters. Use a `noeviction` policy |
| `SECRET_ENCRYPTION_KEY` | — | Fernet key that encrypts signing secrets. Back it up; never change it |
| `COOKIE_SECURE` | `false` | Set `true` in production (HTTPS) |
| `BLOCK_PRIVATE_DESTINATIONS` | `true` | SSRF protection. Turn off only for local development |
| `TRUSTED_PROXY_COUNT` | `0` | Proxies in front of the API; see [Client IPs](#client-ips) |
| `EVENT_RATE_LIMIT_PER_MINUTE` | `600` | Events per account per minute (`0` = unlimited) |
| `DAILY_EVENT_QUOTA` | `10000` | New events per account per UTC day (`0` = unlimited) |
| `AUTH_RATE_LIMIT_PER_MINUTE` | `10` | Login and registration attempts per IP and per email |
| `REPLAY_RATE_LIMIT_PER_MINUTE` | `60` | Deliveries replayed per account per minute |
| `ENDPOINT_MAX_CONCURRENCY` | `10` | Requests in flight to one endpoint, across all workers (`0` = no limit) |
| `DELIVERY_MAX_ATTEMPTS` | `5` | Default for new endpoints (each endpoint can set 1–10) |
| `EVENT_RETENTION_DAYS` | `30` | Delete events, deliveries and attempts after this (`0` = keep forever) |
| `AUDIT_LOG_RETENTION_DAYS` | `365` | Delete audit entries after this (`0` = keep forever) |
| `METRICS_TOKEN` | unset | If set, `GET /metrics` needs `Authorization: Bearer <token>` |
| `ALERT_QUEUE_DELAY_SECONDS` | `300` | Alert when due work has waited longer than this |
| `ALERT_WORKER_SILENCE_SECONDS` | `120` | `/health/ready` reports the worker as `stale` after this |

To change one account's limits, set `event_rate_limit_per_minute` or `daily_event_quota` on its row in `users`
(`NULL` uses the default, `0` is unlimited):

```sql
UPDATE users SET daily_event_quota = 100000 WHERE email = 'big-customer@example.com';
```

## Metrics

`GET /metrics` serves Prometheus metrics. Set `METRICS_TOKEN` in production, since the numbers cover all accounts.

| Metric | Meaning |
| --- | --- |
| `hookflow_http_requests_total{method,route,status}` | API requests (this API process) |
| `hookflow_http_request_duration_seconds{method,route}` | API latency histogram (this API process) |
| `hookflow_deliveries_queued{status}` | Deliveries pending, retrying or being sent |
| `hookflow_delivery_oldest_due_seconds` | How long the longest-waiting due delivery has waited |
| `hookflow_outbox_unpublished` | Queue messages not yet handed to Redis (includes scheduled retries) |
| `hookflow_outbox_oldest_due_seconds` | How long the oldest due one has waited |
| `hookflow_delivery_attempts_recent{result}` | Attempts in the last 5 minutes, `success` or `failure` |
| `hookflow_delivery_latency_ms_recent{quantile}` | Time to send and get a response, last 5 minutes (p50, p95, p99) |
| `hookflow_worker_last_seen_seconds` | Seconds since the worker last ran a scheduled task |
| `hookflow_pipeline_metrics_up` | `0` if the database couldn't be read for the metrics above |

Pipeline metrics are read from Postgres and Redis on each scrape, so they are correct however many processes run.
Request metrics are per API process; with several, scrape each one.

## Alerts

The monitor task checks every minute and writes an `ERROR` log line starting with `ALERT`, with an `alert` field:

| Alert | Fires when | Likely cause |
| --- | --- | --- |
| `delivery_queue_delayed` | A due delivery has waited over `ALERT_QUEUE_DELAY_SECONDS` | Workers stopped or overloaded |
| `outbox_backlog` | A due queue message hasn't reached Redis for that long | Redis down, or the scheduler stopped |

An alert is logged when it starts and every 15 minutes while it lasts, and an `Alert resolved` line follows when it
clears. Point your log provider's alerting at `"level": "ERROR"` lines with an `alert` field.

The monitor runs on the worker, so it can't report its own absence. Watch for that with `/health/ready`
(`"worker": "stale"`) or with Prometheus. Suggested Prometheus rules:

```yaml
groups:
  - name: hookflow
    rules:
      - alert: HookFlowWorkerDown
        expr: hookflow_worker_last_seen_seconds > 120 or absent(hookflow_worker_last_seen_seconds)
        for: 2m
      - alert: HookFlowQueueDelayed
        expr: hookflow_delivery_oldest_due_seconds > 300
        for: 5m
      - alert: HookFlowDeliveryFailureRate
        expr: >
          hookflow_delivery_attempts_recent{result="failure"}
          / clamp_min(sum(hookflow_delivery_attempts_recent), 1) > 0.5
        for: 15m
      - alert: HookFlowApiErrors
        expr: sum(rate(hookflow_http_requests_total{status=~"5.."}[5m])) > 1
        for: 5m
```

A high failure rate often means one customer's endpoint is down rather than a HookFlow problem, so treat it as a
warning.

## Retention

The sweeper deletes, in batches of 500:

- events older than `EVENT_RETENTION_DAYS`, together with their deliveries, attempts, replays and queue messages.
  Events with a delivery still in progress are kept until it finishes.
- audit entries older than `AUDIT_LOG_RETENTION_DAYS`.
- published queue messages after 1 day, and expired idempotency keys.

## Security notes

**SSRF.** Deliveries only go to public addresses. The worker resolves the host itself, refuses the host if *any*
address is private, loopback, link-local, multicast or reserved, and connects to an address from that same lookup.
This blocks DNS rebinding (a host that resolves to a public address when checked and a private one when used).
Redirects are not followed.

**Egress rules.** For defence in depth, also block the workers' outbound traffic to private ranges at the network
level: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`, `169.254.0.0/16` (cloud metadata),
`100.64.0.0/10`, `fc00::/7`, `fe80::/10`. Workers need only Postgres, Redis, and outbound 80/443 to the internet.
Managed platforms like Render don't offer this; on your own infrastructure use security groups or a firewall.

### Client IPs

Audit entries and the per-IP login limit use the caller's IP. Behind a load balancer, every request arrives from the
balancer, so set `TRUSTED_PROXY_COUNT` to the number of proxies that add to `X-Forwarded-For`:

| Setup | Value |
| --- | --- |
| Direct (local development) | `0` |
| One load balancer (e.g. Render) | `1` |
| Dashboard on Vercel calling the API on Render | `2` (Vercel, then Render) |

HookFlow takes the address that many entries from the right, because entries further left come from the client and
can be forged. Proxy behaviour varies between hosts. After a deploy, log in and check that the audit log shows your
own IP. If it shows a cloud provider's address, raise the value by one; if it varies or looks made up, lower it.

With `2`, API calls made directly to Render have only one entry; HookFlow then uses that entry, which the caller can
set. This affects only the IP recorded for direct API calls, not authentication.

## Capacity

Measured with [`loadtest/ingest.py`](../loadtest/ingest.py) on 2026-11-01: Docker Desktop on an 8-core Mac, one
Postgres, one uvicorn process, 8 worker processes delivering to the local test receiver at the same time, 200-byte
events, one endpoint per event.

| Concurrent clients | Throughput | p50 | p95 | p99 |
| --- | --- | --- | --- | --- |
| 1 | 144 events/s | 7 ms | 8 ms | 12 ms |
| 10 | 163 events/s | 60 ms | 83 ms | 102 ms |
| 50 | 156 events/s | 307 ms | 502 ms | 644 ms |
| 50, four API processes | 180 events/s | 92 ms | 721 ms | 930 ms |

- Every request was accepted (no errors), and the workers kept up: the queue was empty within about a second of the
  last event.
- The PRD target (ingestion p95 below 200 ms) is met up to about 10 concurrent clients, roughly 160 events/s.
  Beyond that, requests queue and latency grows.
- Four API processes barely raised throughput, so the limit in this setup is the database (each event is two
  transactions: save, then mark published) and Docker Desktop's disk speed, not the API. A production Postgres on
  its own disk should do better; measure on the real deployment.
- Small hosts are much slower: Render's free instance has a fraction of one CPU.

To run it:

```bash
docker compose run --rm -v "$PWD/loadtest:/loadtest" api python /loadtest/ingest.py \
    --url http://api:8000 --key <api key> --requests 3000 --concurrency 10
```

Raise the test account's limits first (see the script's docstring), or it will hit the 600-per-minute limit.
