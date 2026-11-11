# HookFlow

Webhook delivery platform. Send an event to HookFlow once; it delivers it to every subscribed endpoint, signs it,
retries failures, and records every attempt.

**Status: Milestone 4 (Product Improvements) done, except email alerts.** See [Milestones](#milestones).

## Quick start

Requires Docker.

```bash
cp .env.example .env
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # paste into SECRET_ENCRYPTION_KEY
docker compose up --build
```

| What | Where |
| --- | --- |
| Landing page and dashboard | http://localhost:3000 (dashboard at `/overview`) |
| API + interactive docs | http://localhost:8000/docs |
| Test receiver | `http://receiver:9000/...` from inside HookFlow; watch it with `docker compose logs -f receiver` |

### Try it end to end

1. Open the dashboard, register, and create an API key.
2. Add an endpoint with URL `http://receiver:9000/hooks` and event type `order.created`.
3. Send an event:
   ```bash
   curl -X POST localhost:8000/v1/events \
     -H "Authorization: Bearer $HOOKFLOW_KEY" -H "Content-Type: application/json" \
     -d '{"event_type":"order.created","data":{"order_id":"ORD-101","amount":2499}}'
   ```
4. Watch it arrive in `docker compose logs -f receiver`, then open the event in the dashboard.

The receiver's path controls its response, which is useful for seeing retries and failures:
`/status/503` (retried), `/status/400` (fails straight away), `/slow/15` (times out, retried).

To try replay: add an endpoint at `http://receiver:9000/status/400` and send an event, so the delivery fails. Then
change the endpoint URL to `http://receiver:9000/hooks` and press **Replay** on the event page. Add an
`Idempotency-Key: some-key` header to the curl above and send it twice: you get the same `event_id` both times.
To have the receiver check signatures, put the endpoint's signing secret in `RECEIVER_SECRET` in `.env` and
run `docker compose up -d receiver`.

## Tests

```bash
docker compose run --rm api pytest -q
```

Tests use a separate `hookflow_test` database and Redis DB 15. They cover auth, API keys, tenant isolation,
ingestion, idempotency (including concurrent requests), the outbox with Redis down, signing and secret rotation,
retries, replay, the audit log, the claim/lease logic and crash recovery, plus SSRF and DNS-rebinding protection,
DNS and database outages, ingestion limits and quotas, per-endpoint concurrency, retention, metrics and alerts,
plus team roles and invites, API key scopes, pattern subscriptions, retry schedules and bulk replay.

SDK tests run offline: `cd sdks/python && pytest`, and `cd sdks/node && npm install && npm test`.

Load test: [`loadtest/ingest.py`](loadtest/ingest.py); results and how to run it are in
[docs/operations.md](docs/operations.md#capacity).

## Demo data

To fill a local copy with realistic demo accounts and 30 days of activity:

```bash
docker compose exec api python scripts/seed_demo.py          # --reset to recreate
```

Log in as `maya.demo@example.com` (password `demo123456`) for the full demo. On a public server, set
`DEMO_PASSWORD` first. The default is in this repository. See [backend/scripts/seed_demo.py](backend/scripts/seed_demo.py).

## Documentation

- [docs/PRD.md](docs/PRD.md): product requirements v1.3, the original PRD plus the decisions made while building
  ([PDF](docs/HookFlow-PRD-v1.3.pdf); the original v1.0 is `HookFlow.pdf`).
- [docs/interview-guide.md](docs/interview-guide.md): the whole project explained: architecture, stack choices
  and why, reliability and security design, and common interview questions.
- [docs/api.md](docs/api.md): API reference, delivery behaviour, and how receivers verify signatures.
- [docs/signatures.md](docs/signatures.md): how requests are signed, how receivers check them, and how the
  signature check on each endpoint page works.
- [docs/operations.md](docs/operations.md): running it in production: every setting, metrics, alerts, retention,
  security notes and load-test results.
- [frontend/README.md](frontend/README.md): running the dashboard on its own.
- [sdks/python](sdks/python/README.md) and [sdks/node](sdks/node/README.md): client libraries, including webhook
  signature verification for receivers.

## How it works

```
POST /v1/events ─► one Postgres transaction: event + a delivery per subscribed endpoint + an outbox message each ─► 202
                   then publish those outbox messages to Redis straight away (best effort)

publisher: every 1s ─► publish outbox messages that are due and not yet sent (Redis was down, or a retry is now due)
worker:    claim the delivery atomically (lease) ─► sign + POST ─► record attempt ─► delivered / retrying / failed
                                                                      (a retry writes its outbox message, due later)
sweeper:   every 5s ─► reclaim deliveries whose worker died mid-attempt (lease expired)
                   └─► re-stage due work whose published message never arrived (lost in Redis)
```

- **Postgres is the source of truth.** Redis only carries "go look at delivery X". Every such message is first
  written to the `outbox` table in the same transaction as the work it's about (ingestion, retries, replays, crash
  recovery). If Redis is down, the message waits in Postgres and the publisher sends it once Redis is back. Events
  are still accepted while Redis is down.
- **Claims are atomic.** A worker moves a delivery to `processing` with one conditional `UPDATE`, so two workers
  can never send the same attempt.
- **Delivery is at-least-once.** A worker crash after the receiver got the request but before the result was saved
  leads to a retry with the same event ID. Receivers should de-duplicate on `HookFlow-Event-Id`. A message published
  twice is harmless, because the claim only succeeds once.
- **Ingestion is idempotent** with an `Idempotency-Key` header: the same key and body return the original event,
  while a different body with the same key is rejected (`409`).
- **Replay** resets a failed delivery so it's sent again, with the same event ID and a fresh retry budget. Old
  attempts are kept. See [docs/api.md#replay](docs/api.md#replay).

| Path | What |
| --- | --- |
| `backend/app/routers/` | API routes |
| `backend/app/worker/engine.py` | Claim, send, record, sweep |
| `backend/app/outbox.py` | Transactional outbox and publisher |
| `backend/app/replay.py` | Replay rules |
| `backend/app/audit.py` | Audit log |
| `backend/app/worker/retry.py` | Retry policy |
| `backend/app/urlguard.py` | Destination URL checks (SSRF) |
| `backend/app/models.py` | Schema (migrations in `backend/alembic/versions/`) |
| `frontend/` | Next.js dashboard |
| `receiver/` | Local test receiver |

## Configuration

Backend settings come from environment variables (see `backend/app/config.py`). The main ones:

| Variable | Default | Notes |
| --- | --- | --- |
| `DATABASE_URL` | | `postgresql+psycopg://…` |
| `REDIS_URL` | | |
| `SECRET_ENCRYPTION_KEY` | required | Fernet key that encrypts signing secrets at rest |
| `BLOCK_PRIVATE_DESTINATIONS` | `true` | Docker Compose sets `false` so the local receiver works. Keep it `true` in production. |
| `COOKIE_SECURE` | `false` | Set `true` behind HTTPS |
| `DELIVERY_MAX_ATTEMPTS` | `5` | Default for new endpoints; each endpoint can set 1–10 |
| `RETRY_BASE_DELAY_SECONDS` / `RETRY_MAX_DELAY_SECONDS` | `30` / `21600` | Backoff is base × 4ⁿ with ±25% jitter, capped |
| `REPLAY_RATE_LIMIT_PER_MINUTE` | `60` | Deliveries replayed per account per minute |
| `IDEMPOTENCY_KEY_TTL_HOURS` | `24` | |
| `SECRET_ROTATION_GRACE_SECONDS` | `86400` | Default grace period when rotating a signing secret |
| `DELIVERY_TIMEOUT_SECONDS` | `10` | |
| `MAX_PAYLOAD_BYTES` | `1048576` | |
| `EVENT_RATE_LIMIT_PER_MINUTE` / `DAILY_EVENT_QUOTA` | `600` / `10000` | Per account; `0` = unlimited |
| `EVENT_RETENTION_DAYS` | `30` | Events and their history are deleted after this |
| `TRUSTED_PROXY_COUNT` | `0` | Proxies in front of the API, for real client IPs |
| `METRICS_TOKEN` | unset | Protects `GET /metrics` |

The full list is in [docs/operations.md](docs/operations.md#settings).

Run exactly one `beat` process (it schedules the outbox publisher and the sweeper). You can run as many `worker`
processes as you like.

## Milestones

**Milestone 1 (Core MVP):** user auth, API keys, endpoint registration, event ingestion, Postgres persistence,
background delivery, delivery history, and the dashboard.

**Milestone 2 (Reliability):**

- Configurable retries: exponential backoff with jitter, and a per-endpoint `max_attempts`
- Delivery attempt history
- HMAC signatures, with a grace period when rotating secrets
- Idempotency keys on `POST /v1/events`
- Manual replay, from the API and the dashboard, with a replay history
- A durable outbox for every queue message
- Worker crash recovery
- Audit log (API and dashboard)

**Milestone 3 (Public Beta Hardening):**

- SSRF: connections go to the exact address that was checked, which blocks DNS rebinding
- Ingestion limits: 600 events per minute and 10,000 per day per account, configurable per account, with
  rate-limit headers
- At most 10 requests in flight to one endpoint at a time
- Prometheus metrics at `/metrics`, and logged alerts when work gets stuck
- Retention: events and their history are deleted after 30 days, audit entries after a year
- Database outages return `503` with `Retry-After`; DNS failures are retried
- Real client IPs behind proxies, for audit entries and login limits
- Attempt counts in the dashboard restart after a replay
- Load tests, and a single-container start script that restarts if a process dies

**Milestone 4 (Product Improvements):**

- Team accounts: invite people by link, with owner, admin, developer and viewer roles; switch between accounts
- Scoped API keys, e.g. a key that can only send events
- Pattern subscriptions such as `order.*`
- Custom retry schedules per endpoint
- Bulk replay of failed deliveries, with a dry run, from the API and the dashboard
- Endpoint health badges (healthy, degraded, failing) over the last 24 hours
- [Python and Node SDKs](sdks/): send events, manage endpoints, replay, and verify webhook signatures

**Next:** email alerts when an endpoint keeps failing.
