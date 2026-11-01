# HookFlow Work Log

A record of what was done in each work session, newest first. Add an entry at the end of every session.

Each entry covers: what was built or changed, decisions made, how it was checked, and what's left.

---

## 2026-11-01 — Milestone 3 (Public Beta Hardening)

**Outcome:** All Milestone 3 items in the PRD are done, and both known issues are fixed. The PRD is now v1.2
(`docs/PRD.md`, `docs/HookFlow-PRD-v1.2.pdf`, which replaces the v1.1 PDF). Nothing is committed yet.

### Built
- **SSRF / DNS rebinding:**
  - `app/urlguard.py` has `GuardedBackend` and `GuardedTransport`. The HTTP client resolves the host once, rejects
    it if any address is internal, and connects to an address from that same lookup.
  - TLS still checks the hostname.
  - DNS failures are now retried (they used to fail permanently).
- **Ingestion limits:**
  - 600 events per minute and 10,000 per UTC day per account. New nullable `users` columns override them; `0` means
    unlimited.
  - `X-RateLimit-*` and `X-Quota-*` headers. `429 rate_limited` / `quota_exceeded` with `Retry-After`.
  - Idempotent retries and failed requests don't use quota. Limits fail open if Redis is down.
- **Per-endpoint concurrency:**
  - `app/worker/concurrency.py` is a Redis sorted-set semaphore, default 10 per endpoint, with slots that expire.
  - A busy endpoint pushes the delivery back 1–3s without using an attempt.
- **Metrics:**
  - `app/metrics.py` serves `GET /metrics` (Prometheus): request count and latency per route template.
  - `app/ops.py` reads pipeline state from the DB and Redis at scrape time: queue depth, oldest due delivery,
    outbox backlog, recent success and latency, worker heartbeat.
  - Optional `METRICS_TOKEN`.
- **Alerts:**
  - A `hookflow.monitor` beat task runs every 60s and logs `ALERT ...` at ERROR, de-duplicated for 15 minutes, with
    a "resolved" line when it clears.
  - `/health/ready` reports the worker as `ok`/`stale`/`unknown` without failing the check.
- **Retention:** the sweeper deletes events older than 30 days (cascading to deliveries, attempts, replays and
  outbox) unless a delivery is still active, and audit entries after 365 days.
- **Database outages:** `OperationalError` maps to `503 service_unavailable` with `Retry-After: 5`.
- **Client IPs:**
  - `app/clientip.py` with `TRUSTED_PROXY_COUNT` takes the Nth `X-Forwarded-For` entry from the right.
  - Used for audit IPs and the per-IP login limit. Behind a proxy, that limit had been shared by every user.
- **Attempt display:** deliveries also return `run_attempt_count` / `run_max_attempts`. The dashboard shows those, with
  the lifetime total in a tooltip, and the "Sending now (attempt x of y)" text is no longer off by one.
- **`start.sh`:** watches the worker and API, and exits with code 1 if either stops, so Render restarts the
  container.
- **Migration `0003`:** the user columns, plus indexes on `events.created_at`, `audit_logs.created_at` and
  `delivery_attempts.completed_at`.
- **Load test:** `loadtest/ingest.py`, an async ingester that then waits for the queue to drain.
- **Docs:**
  - New `docs/operations.md`: settings, metrics, alerts with Prometheus rules, retention, egress rules,
    trusted-proxy guidance, capacity.
  - Updated `docs/api.md`, README and `.env.example`.
  - PRD: statuses, retention and deployment decisions, known issues marked fixed.
- New dependency: `prometheus-client==0.21.1`.

### Checked
- `pytest`: 118 passed (31 new in `tests/test_hardening.py`), including:
  - a real local HTTP server proving one DNS lookup and a pinned connection
  - DB down for the API, worker, outbox and metrics
- Frontend `typecheck` and `build` pass.
- Live in Docker:
  - migration to 0003
  - an event delivered, with the limit headers on the response
  - `/metrics` populated, with the worker heartbeat
- `start.sh` in a container: all three processes start; killing the worker makes the container exit with code 1.
- Load test (Docker Desktop, one API process):
  - 1 client: p95 8 ms.
  - 10 clients: 163 events/s, p95 83 ms (meets the PRD's 200 ms target).
  - 50 clients: about 156 events/s, p95 502 ms.
  - Four API processes reached only 180/s, so the limit here is the database or disk, not the API.
  - No errors; the workers kept up.

### Left / notes
- Push to deploy. Render runs the migration on start.
- On Render, set `TRUSTED_PROXY_COUNT` (probably `2` with the Vercel dashboard) and `METRICS_TOKEN`. Then check the
  audit log shows the user's real IP.
- Request metrics are per API process. The monitor can't report a dead worker (use `/health/ready` or Prometheus).
- Next: Milestone 4.

---

## 2026-11-01 — Deployment prep

**Outcome:** The app now accepts the plain `postgres://` and `postgresql://` database URLs that hosts like Render
provide. The user is setting up deployment (Render + Vercel) and CI/CD (GitHub Actions) themselves.

### Changed
- `backend/app/config.py`: `DATABASE_URL` values starting `postgres://` or `postgresql://` are rewritten to
  `postgresql+psycopg://`, so SQLAlchemy uses the installed psycopg 3 driver.
- `backend/tests/test_units.py`: a test for that conversion.
- A `render.yaml` and a CI workflow were drafted and then removed at the user's request.

### Checked
- `pytest`: 87 passed.

---

## 2026-10-30 — PRD updated to v1.1

**Outcome:** The PRD now matches what was built. The original `HookFlow.pdf` (v1.0) is unchanged. The updated
version is `docs/PRD.md` (editable source) and `docs/HookFlow-PRD-v1.1.pdf` (31 pages, exported from the Markdown).

### Changed in the PRD
- All original requirement text is kept. Additions are marked **Decision (v1.1)** or **Status (v1.1)**.
- Recorded concrete behaviour for:
  - the retry policy (codes, delays, per-endpoint limits)
  - signature format and rotation grace
  - idempotency keys
  - replay rules and storm protection
  - endpoint delete and disable
  - delivery format and leases
- Answered the open questions: subscriptions use exact matches plus `*`; deletion archives; retries can be customised
  per endpoint (max attempts only). Still open: retention, deployment provider, and public vs invite-only (recommended:
  invite-only until Milestone 3).
- Added FR-14 (Audit Log), the full v1 API table (kept both replay endpoints with different scopes), and three new
  data model entities (sessions, idempotency keys, delivery replays).
- Rewrote the state machine as a diagram plus a transitions table, adding cancel, replay and lease-expiry.
- Added status to every functional requirement, the SSRF and resource checklists, the release plan, and the
  Definition of Done.
- Added a "Known issues" list: the audit IP behind the proxy, and the attempt total growing after replays.
  Milestone 4 gained pattern subscriptions, scoped API keys and bulk replay.
- README links to the new PRD.

### Checked
- Rendered the PDF and checked the first page and the state-machine section visually.

---

## 2026-10-30 — Milestone 2 (Reliability)

**Outcome:** All Milestone 2 items in the PRD are done. Transient failures are retried, duplicate ingestion is
handled with idempotency keys, and unfinished work is recovered after a worker or Redis restart. This meets the PRD's
Milestone 2 exit criteria.

### Built
- **Idempotency keys** on `POST /v1/events` (`Idempotency-Key` header):
  - Same key and body → the original response with `Idempotent-Replayed: true`. Different body → `409 idempotency_key_reused`.
  - Keys are per account and kept for 24h. Concurrent requests with the same key create one event.
  - New table `idempotency_keys`.
- **Transactional outbox** (`backend/app/outbox.py`, table `outbox`):
  - Every queue message is written in the same transaction as its work: ingestion, retries, replays and crash recovery.
  - The API publishes right after commit. A publisher task runs every 1s through beat and sends anything left over,
    including retries that have come due.
  - Events are accepted while Redis is down and are delivered once it's back.
- **Manual replay**:
  - API: `POST /v1/deliveries/{id}/replay`, `POST /v1/events/{id}/replay` (optional `endpoint_ids`), and
    `GET /v1/deliveries/{id}/replays`.
  - Behaviour: same event and delivery ID, old attempts kept, numbering continues, fresh retry budget with normal backoff.
  - Rules: only failed or cancelled deliveries; the endpoint must be enabled; the current URL rules apply.
    Rate limit: 60 deliveries a minute per account.
  - New table `delivery_replays`.
- **Per-endpoint `max_attempts`** (1–10, default 5). It applies to new deliveries.
- **Secret rotation grace period** (default 24h, 0–7 days). Both secrets sign during it (`v1=<new>,v1=<old>`).
- **Audit log** (`audit_logs` table, `GET /v1/audit-logs`). Records register, login, API key changes, endpoint
  create/update (field-level changes)/archive, secret viewed or rotated, and replays. Secrets are never stored in it.
- **Sweeper housekeeping:**
  - Deletes published outbox rows older than 1 day and expired idempotency keys.
  - Re-stages work whose published message was lost in Redis.
- **Dashboard** (built by a helper agent):
  - Replay buttons with inline confirmation, on event detail, deliveries and endpoint pages. Includes "Replay failed
    deliveries" for a whole event.
  - Replay markers in the attempt history.
  - Max attempts on the endpoint forms.
  - A rotate-secret grace picker and a grace-period banner.
  - A new Audit log page with filters; the idempotency key shows on the event page.
- Migration `0002_reliability`. Docs updated in `docs/api.md` and `README.md`.

### Decisions
- **Replay resets the same delivery** rather than creating a new one, so the event ID, history and dashboard links stay
  the same. Each delivery has `retry_base_attempt`, so backoff and "gave up after N" count from the last replay.
- **A dedicated outbox table** replaced the M1 approach of re-queuing from the deliveries table. The PRD asks for it
  explicitly, and it makes "Redis was down" recoverable in a way that can be inspected.
- **The secret is only fetched when Reveal is clicked**, because each view is now audited.
- `docker-compose.yml`: `migrate` and `beat` now mount `./backend` like `api` and `worker`. They had been running a
  stale image without the new code.

### Bugs found and fixed
- `migrate` and `beat` ran an old image ("Can't locate revision 0002", and no outbox schedule). Fixed by mounting the
  source folder and rebuilding.
- The endpoint response showed a grace-period end time even after it had passed. It's now null once expired.

### Checked
- `docker compose run --rm api pytest -q`: **86 passed**. 26 tests are new, in `tests/test_reliability.py`.
- Live run: same key twice gave the same event; a different body gave 409; a 400 delivery failed; after fixing the
  URL, replay delivered it as attempt 2; a second replay gave 409; the audit trail was correct.
- Live outage test: with Redis stopped, an event was accepted in 9ms and its message waited in the outbox. After
  Redis restarted it was published and delivered.
- Migration upgrades and downgrades cleanly; `alembic check` shows no drift.
- Dashboard: `npm run build` passes. The helper agent checked replay, rotation, audit log and forms in headless Chrome.

### Left to do / known issues
- **Audit IPs for dashboard actions** show the frontend container's IP, because the API sees the Next.js proxy, not
  the browser. The fix is to trust `X-Forwarded-For` only from the proxy (uvicorn `--proxy-headers
  --forwarded-allow-ips`), which needs a fixed network setup. Moved to Milestone 3 deployment work.
- `max_attempts` on a delivery is a running total: each replay adds the endpoint's limit. After many replays the UI
  can show something like "63/65". It's correct but could read better.
- **Milestone 3:** DNS-rebinding IP pinning, egress rules, ingestion and per-account rate limits, Prometheus metrics,
  load tests, retention for events and attempts, production deployment.
- Dev data: test accounts `m2-smoke-*`, `m2-outage-*` and `dash-m2-92396361@example.com` were added to the local DB.
- The project still isn't a git repository.

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
