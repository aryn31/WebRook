# HookFlow Work Log

A record of what was done in each work session, newest first. Add an entry at the end of every session.

Each entry covers: what was built or changed, decisions made, how it was checked, and what's left.

---

## 2026-10-30 — Milestone 1 (Core MVP)

Also started this work log. Every work session from now on ends with an entry here.

**Outcome:** A developer can register, create an API key, add an endpoint, send an event, receive it, and inspect
the result in the dashboard. This meets the Milestone 1 exit criteria in the PRD.

### Built

**Backend** (`backend/`, FastAPI + SQLAlchemy + Alembic + Postgres)
- Accounts: register, log in and log out with server-side sessions in an HttpOnly cookie. Passwords are hashed
  with Argon2. Login and register are rate-limited per IP and per email, using Redis.
- API keys: the full key is shown only when created. Only a SHA-256 hash and a non-secret prefix are stored. Keys
  can be revoked. Keys can't be used to manage other keys; that's dashboard only.
- Endpoints: create, list, get, edit, enable or disable, and archive. Subscriptions are exact event types or `*`.
  Signing secrets are encrypted at rest with Fernet and can be revealed or rotated. Limit of 50 endpoints per account.
- Events: `POST /v1/events` saves the event and one delivery per matching endpoint in a single transaction, then
  returns 202. There's a 1 MiB body limit. Events can be listed (with filters), fetched, and their deliveries listed.
- Deliveries: list with filters, get one, and view its attempt history. Stats endpoint covers 24h, 7d and 30d.
- Health checks: `/health/live` and `/health/ready`.
- Errors use one JSON shape everywhere. Logs are structured JSON.
- IDs are prefixed and sort by creation time (`evt_…`, `dlv_…`). List endpoints use cursor pagination.

**Delivery engine** (`backend/app/worker/`, Celery + Redis)
- A worker claims a delivery with a single atomic `UPDATE`, which also sets a 60-second lease. It then signs the
  request (HMAC-SHA256 over `timestamp.body`), sends it with a 10s timeout and no redirects, keeps at most 4 KiB of
  the response, and records the attempt.
- Retries happen on 408, 429, 5xx, timeouts and connection errors, up to 5 attempts in total. Waits grow
  exponentially with jitter (about 30s, 2m, 8m, 32m), and a `Retry-After` header is honoured. Any other 4xx fails
  immediately.
- A sweeper runs every 5 seconds through Celery beat. It re-queues due work, which covers lost queue messages and
  retries whose time has come. It also reclaims deliveries whose worker died mid-attempt.
- Disabling or archiving an endpoint cancels its unsent deliveries.
- SSRF basics: only http and https are allowed. Private, loopback, link-local and reserved IPs are blocked both at
  registration and after DNS lookup at send time.

**Dashboard** (`frontend/`, Next.js 15, built by a helper agent)
- Pages: login and register, overview (stats, chart, recent failures, onboarding checklist), events, event detail
  (payload, deliveries, attempt history), deliveries, endpoints, endpoint detail (edit, secret, test event,
  archive), and API keys.
- Calls the API through a same-origin `/api` proxy so the session cookie works. Supports light and dark mode.

**Other**
- `receiver/`: a test webhook receiver. Its path sets the response: `/hooks` returns 200, `/status/503` returns
  503, and `/slow/15` waits 15 seconds. It can also check signatures.
- `docker-compose.yml`: postgres, redis, migrate, api, worker, beat, receiver, frontend.
- Docs: `README.md`, and `docs/api.md` (API reference plus signature verification in Python and Node).

### Decisions
- **Postgres is the source of truth for delivery work.** Redis only carries "deliver X" messages. This makes the
  sweeper enough to recover lost work, so a separate outbox table wasn't needed yet.
- **Some Milestone 2 work was pulled forward:** signing, retries, attempt history and crash recovery. The delivery
  engine needed them anyway.
- **Endpoint deletion archives instead of deleting,** so delivery history is kept.
- **Delivery is at-least-once.** Receivers should de-duplicate on `HookFlow-Event-Id`.

### Bugs found and fixed
- The sweeper's `SELECT … FOR UPDATE` failed because of an automatic outer join. Fixed by making the relationships
  inner joins and locking only the `deliveries` table (`of=Delivery`).
- Alembic couldn't import the app. Fixed by adding `prepend_sys_path = .` to `alembic.ini`.

### Checked
- `docker compose run --rm api pytest -q`: 60 passed. Covers auth, API keys, tenant isolation on every route,
  ingestion, the payload limit, signatures, retries, redirects, timeouts, max attempts, atomic claims, lost-message
  recovery, worker-crash recovery, and SSRF checks.
- Manual end-to-end run with the receiver: 200 → delivered, 503 → retrying (attempt 2/5 seen), 400 → failed.
- The dashboard builds (`npm run build`, no type errors). Login and the API proxy work at localhost:3000.

### Left to do
- **Milestone 2:** idempotency keys on `POST /v1/events`, manual replay (dashboard and API), per-endpoint retry
  settings, a grace period when rotating secrets, audit logs.
- **Milestone 3:** pin the checked IP so DNS can't change before the request is sent, egress rules, rate limits on
  ingestion and per account, Prometheus metrics, load tests, retention cleanup, production deployment.
- Dev data: the `dev@example.com` account and the agent's `dashboard-smoke-test@example.com` account are in the
  local database. `docker compose down -v` wipes them.
- The project isn't a git repository yet.
