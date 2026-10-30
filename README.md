# HookFlow

Webhook delivery platform. Send an event to HookFlow once; it delivers it to every subscribed endpoint, signs it,
retries failures, and records every attempt.

**Status: Milestone 1 (Core MVP).** See [What's in Milestone 1](#whats-in-milestone-1).

## Quick start

Requires Docker.

```bash
cp .env.example .env
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # paste into SECRET_ENCRYPTION_KEY
docker compose up --build
```

| What | Where |
| --- | --- |
| Dashboard | http://localhost:3000 |
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
To have the receiver check signatures, put the endpoint's signing secret in `RECEIVER_SECRET` in `.env` and
run `docker compose up -d receiver`.

## Tests

```bash
docker compose run --rm api pytest -q
```

Tests use a separate `hookflow_test` database and Redis DB 15. They cover auth, API keys, tenant isolation,
ingestion, signing, retries, the claim/lease logic and crash recovery.

## Documentation

- [docs/api.md](docs/api.md): API reference, delivery behaviour, and how receivers verify signatures.
- [frontend/README.md](frontend/README.md): running the dashboard on its own.

## How it works

```
POST /v1/events ─► one Postgres transaction: event + one delivery row per subscribed endpoint ─► 202
                   then a best-effort message to Redis ("deliver dlv_…")

worker:  claim the delivery atomically (lease) ─► sign + POST ─► record attempt ─► delivered / retrying / failed
sweeper: every 5s ─► re-queue due deliveries (new work whose message was lost, retries now due)
                 └─► reclaim deliveries whose worker died mid-attempt (lease expired)
```

- **Postgres is the source of truth.** Redis only carries "go look at delivery X". If Redis loses a message or is
  down when an event comes in, the sweeper finds the work in Postgres and queues it again.
- **Claims are atomic.** A worker moves a delivery to `processing` with one conditional `UPDATE`, so two workers
  can never send the same attempt.
- **Delivery is at-least-once.** A worker crash after the receiver got the request but before the result was saved
  leads to a retry with the same event ID. Receivers should de-duplicate on `HookFlow-Event-Id`.

| Path | What |
| --- | --- |
| `backend/app/routers/` | API routes |
| `backend/app/worker/engine.py` | Claim, send, record, sweep |
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
| `DELIVERY_MAX_ATTEMPTS` | `5` | |
| `DELIVERY_TIMEOUT_SECONDS` | `10` | |
| `MAX_PAYLOAD_BYTES` | `1048576` | |

Run exactly one `beat` process (the sweeper). You can run as many `worker` processes as you like.

## What's in Milestone 1

Everything the PRD lists for Milestone 1: user auth, API keys, endpoint registration, event ingestion, Postgres
persistence, background delivery, delivery history, and the dashboard.

Some Milestone 2 pieces were pulled in early because the delivery engine needed them anyway:

- HMAC signatures
- Retries with exponential backoff
- Attempt history
- Crash recovery

**Still to do:**

- **Milestone 2:** idempotency keys on `POST /v1/events`, manual replay, per-endpoint retry settings, a
  secret-rotation grace period (rotation currently takes effect immediately), audit logs.
- **Milestone 3:** pinning the checked IP to block DNS rebinding, network egress rules, rate limits on ingestion and
  per account (only login and register are limited today), Prometheus metrics, load tests, retention cleanup,
  production deployment.
