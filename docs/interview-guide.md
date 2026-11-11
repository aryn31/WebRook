# HookFlow: project guide for interviews

What HookFlow is, how it works, what it's built with and why, and how to answer the questions interviewers
usually ask about it.

Live: https://web-rook.vercel.app (dashboard) and https://hookflow-api-pux4.onrender.com (API).

---

## 1. The 30-second pitch

> HookFlow is a webhook delivery platform. A company sends an event to HookFlow once, for example
> `order.paid`, and HookFlow delivers it to every server that subscribed to it. It signs each request so the
> receiver knows it's genuine, retries with backoff when the receiver is down, and records every attempt so
> nothing is lost silently. On top of that it has a dashboard, teams, failure alerts, a customer portal, a
> receiver security check and shareable proof-of-delivery pages.
>
> It's a FastAPI backend with Postgres and Redis, Celery workers, and a Next.js dashboard, deployed on Render and
> Vercel, with 246 automated tests.

## 2. The problem it solves

A **webhook** is an HTTP request one system sends to another when something happens ("payment succeeded").
Sending one request is easy. Sending them reliably is not:

- **Receivers go down.** If their server is down for 10 minutes, the events from those 10 minutes must not be lost.
- **Requests can be faked.** A webhook URL is public, so the receiver needs a way to check a request really came
  from you.
- **Nobody can see what happened.** When a customer says "we never got it", you need a record of every attempt.
- **Malicious URLs.** Users choose the URL. Without checks, someone could point it at your own internal network
  (`http://169.254.169.254/` is the cloud metadata service). This attack is called SSRF.

Companies like Stripe and GitHub built this internally. HookFlow is that system as a service, similar to Svix or
Hookdeck.

## 3. Architecture

```
  Customer's app                         HookFlow                                   Receivers
 ───────────────        ┌──────────────────────────────────────────────┐        ─────────────
                        │                                              │
  POST /v1/events ─────►│  FastAPI API ──(one transaction)──► Postgres │
  (API key)             │      │          event + deliveries + outbox  │
                        │      │                                │      │
                        │      └── publish ──► Redis queue ◄────┘      │
                        │                         │   (outbox publisher)│
                        │                         ▼                    │
                        │                  Celery workers ─── signed POST ───► https://their.server/hooks
                        │                         │                    │
                        │              record attempt, schedule retry  │
                        │                         ▼                    │
                        │                     Postgres                 │
                        └──────────────────────────────────────────────┘
                                   ▲
  Next.js dashboard ───────────────┘  (same API, session cookie, via /api proxy)
```

**Components:**
- **API (FastAPI):** accepts events, manages endpoints, keys, teams and so on.
- **Postgres:** the source of truth for everything, including which deliveries are due.
- **Redis:** the job queue (through Celery), rate-limit counters and per-endpoint concurrency slots.
- **Workers (Celery):** send the HTTP requests and record results.
- **Beat (the Celery scheduler):** runs three periodic jobs:
  - the outbox publisher, every second;
  - the sweeper, every 5 seconds;
  - the monitor, every minute.
- **Dashboard (Next.js):** the web app for users.

## 4. Tech stack: what and why

| Part | Choice | Why this one |
|---|---|---|
| API | **FastAPI** (Python) | Type hints double as request validation (Pydantic). It generates OpenAPI docs automatically, and it's fast to write. |
| Validation | **Pydantic v2** | Every request and response has a schema, so bad input is rejected with a clear 422 before any logic runs. |
| Database | **PostgreSQL** | Transactions and row locks are essential for the delivery engine. JSONB stores event payloads. |
| ORM and migrations | **SQLAlchemy 2** and **Alembic** | Typed models. Migrations are versioned files (0001 to 0010) applied on every deploy. |
| Queue | **Redis + Celery** | Mature, with retries, scheduling (beat) and multiple workers. Redis also does rate limiting. |
| HTTP client | **httpx** | Timeouts, streaming (so it can stop reading huge responses) and a pluggable transport, used for SSRF protection. |
| Passwords | **Argon2** (argon2-cffi) | The current recommended password hash: slow and memory-hard, so stolen hashes are hard to crack. |
| Secrets at rest | **Fernet** (cryptography) | Endpoint signing secrets must be readable later (to sign), so they're encrypted, not hashed. |
| Receipts | **Ed25519** | Public-key signatures, so anyone can verify a proof receipt without a shared secret. |
| Frontend | **Next.js 15** (App Router, React, TypeScript) | Server and client components, routing, and a built-in proxy (`/api` rewrite) so the session cookie stays on one domain. |
| Styling | Plain CSS with design tokens | Light and dark themes come from swapping CSS variables. No CSS framework to fight. |
| Local dev | **Docker Compose** | One command starts Postgres, Redis, API, worker, beat, dashboard and a test receiver. |
| Hosting | **Render** (API and worker) and **Vercel** (dashboard) | Free tiers. Render runs Docker, and Vercel is made for Next.js. |
| CI | **GitHub Actions** | Runs backend tests and a frontend type check and build on every push. |
| Email | Gmail API, Brevo or SMTP (switchable) | Render's free plan blocks SMTP ports, so email can go over HTTPS APIs instead. |

## 5. The life of one event

1. **The customer sends it:** `POST /v1/events` with an API key, an `event_type` and `data`.
2. **The API checks:**
   - the API key (looked up by its SHA-256 hash; keys are never stored in plain text);
   - its scope (`events:write`);
   - the payload size (1 MiB at most);
   - the per-minute rate limit and the daily quota.
3. **Idempotency:** if an `Idempotency-Key` header was sent before, the API returns the original event instead of
   creating a duplicate. A row lock (`SELECT … FOR UPDATE`) makes two identical requests at the same moment safe.
4. **Fan-out, in one database transaction:**
   - save the event;
   - find every enabled endpoint subscribed to that type (`order.paid`, `order.*` or `*`);
   - create one delivery row per endpoint;
   - add one outbox message per delivery.
5. **The response:** `202 Accepted` with the event ID. The customer doesn't wait for delivery.
6. **Publish:** right after commit, the API pushes the messages to Redis. If that fails, the outbox publisher picks
   them up within a second.
7. **A worker claims the delivery** with one atomic `UPDATE … WHERE status IN (pending, retrying) AND due`. That
   gives it a 60-second lease, so two workers can never send the same delivery at once.
8. **The worker sends it:**
   - builds the JSON body;
   - signs it (section 7);
   - sends it through the SSRF-safe transport, with a 10-second timeout and no redirects followed;
   - reads at most 4 KiB of the response.
9. **The worker records the result:**
   - **2xx:** delivered.
   - **408, 429 or 5xx, or a timeout or connection error:** retry later. The delay grows about 4x each time (30s,
     2m, 8m, 32m…) with ±25% random jitter, capped at 6 hours, and respects the receiver's `Retry-After` header.
   - **Other 4xx or a redirect:** failed for good, because retrying won't help.
   - After `max_attempts` (5 by default) failures, the delivery is marked failed.
10. **Afterwards:** the dashboard shows every attempt. After 5 failures in a row, the owner gets an alert email,
    and a recovery email when it works again. Failed deliveries can be replayed.

## 6. Reliability design (the part interviewers like most)

### Transactional outbox

**The problem:** saving to Postgres and pushing to Redis are two separate systems. If the app crashes between
them, either a delivery exists that nobody will send, or a job exists for data that was rolled back.

**The fix:** the queue message is written to an `outbox_messages` table **in the same transaction** as the
delivery, so both are saved or neither is. A publisher then moves unpublished messages to Redis. A message might
be published twice, but that's harmless because claiming a delivery is atomic (step 7), so the duplicate does
nothing.

### Postgres is the source of truth, Redis is just a hint

A queue message only says "go look at delivery X". The worker re-checks the database before doing anything. So:
- if Redis loses everything (restart without persistence), the **sweeper** finds due deliveries in Postgres and
  re-queues them;
- if a worker dies mid-send, its lease expires and the sweeper reclaims the delivery.

### At-least-once delivery

A worker can crash after the receiver got the request but before saving the result. Then it will be sent again.
Exactly-once over HTTP is impossible, so HookFlow promises **at-least-once** and makes duplicates easy to handle:
the event ID stays the same on every retry (`webhook-id` header), so receivers can skip IDs they've seen.

### Retries with exponential backoff and jitter

- **Exponential:** a struggling server gets more breathing room each time.
- **Jitter:** spreads retries out, so 10,000 failed deliveries don't all retry in the same second (the "thundering
  herd").
- **Retry-After:** respected, because the receiver knows best when it'll be ready.
- **Custom schedules:** each endpoint can have its own retry schedule and maximum attempts.

### Protecting receivers

- **Concurrency limit:** at most 10 requests in flight per endpoint, across all workers. It uses a Redis sorted set
  of slots that expire on their own, so a crashed worker can't hold a slot forever.
- **Fail open:** if Redis is down, the limit is skipped, because delivering matters more than the limit.

### Idempotent ingestion

`Idempotency-Key` means a client can safely retry `POST /v1/events` after a network error without creating the
event twice. Keys are remembered for 24 hours. Reusing a key with a different body is an error.

## 7. Security design

### Webhook signatures (how receivers know a request is genuine)

Each endpoint has a secret (`whsec_…`). Every request carries an **HMAC-SHA256** of the timestamp plus the body,
keyed with that secret. The receiver recomputes it and compares:

- **Body changed** → signature doesn't match → reject.
- **Old timestamp (more than 5 minutes)** → reject, which stops replays of captured requests.
- **Comparison:** must be constant-time (`hmac.compare_digest`), so timing doesn't leak the signature.

Two formats are sent on every request:
- HookFlow's own (`HookFlow-Signature: v1=<hex>`);
- the **Standard Webhooks** spec (`webhook-id`, `webhook-timestamp`, `webhook-signature`), so receivers can use
  off-the-shelf libraries. Tests check it against the official library.

**Secret rotation:** for a grace period (24 hours by default), both the old and new secret sign each request, so
receivers can switch without downtime.

### SSRF protection

Users choose the destination URL, so HookFlow must never send requests into its own network:

- **When the URL is saved:** only http/https, no embedded credentials, no private IP addresses.
- **When sending:** a custom httpx transport resolves the hostname itself, refuses any private, loopback,
  link-local or reserved address, then connects to **the exact IP it just checked**.
  - This stops **DNS rebinding**, where DNS returns a safe IP during the check and an internal IP when connecting.
  - TLS still verifies the certificate against the hostname.
- **Redirects:** not followed, because a redirect could point inside the network.

### Authentication and authorisation

- **Dashboard sessions:**
  - a random token in an `HttpOnly` cookie (`hf_session`), so JavaScript can't read it;
  - only its hash is stored in the database;
  - users can see and sign out their sessions on other devices.
- **API keys:** shown once, stored as SHA-256 hashes, each with **scopes** (`events:write`, `deliveries:read`…),
  so a leaked read-only key can't send events.
- **Teams:** roles are owner, admin, developer and viewer. Every route needs one permission, and roles map to
  permission sets.
- **Multi-tenancy:** every query filters by account. Tests check that account B gets 404 for account A's data
  (404 rather than 403, so it doesn't reveal that something exists).
- **Email verification and password reset:**
  - 6-digit codes, stored hashed, valid for 15 minutes, limited to 5 tries;
  - resending is limited too.
- **Passwords:** hashed with Argon2.
- **Rate limits:** Redis fixed-window counters on login, ingestion, replays and so on. If Redis is down they fail
  open.
- **Audit log:** every important action (key created, secret viewed, endpoint changed, replay) with who, when and
  from which IP.

## 8. Features beyond basic delivery

| Feature | What it does | Interesting detail |
|---|---|---|
| **Replay** | Re-send failed deliveries, one by one, per event, or in bulk with filters | Same event ID; gets a fresh retry budget; rate limited; dry-run mode for bulk |
| **Failure alerts** | Email after 5 failures in a row, and a recovery email | Decided inside the attempt transaction, sent after commit, so a rollback never sends a false alert |
| **Receiver security check** | Sends 5 test requests (valid, wrong signature, edited body, old timestamp, no signature) and grades whether the receiver checks signatures | No competitor has this. Verdicts: pass, partial, fail, inconclusive |
| **Customer portal** | Embeddable page where *your* customers manage their own endpoints | Stateless signed token in the URL fragment (never sent to servers or in Referer headers); every query scoped to account and consumer |
| **Proof-of-delivery links** | A public page proving what happened to one delivery, to send to a customer who says "we never got it" | Ed25519-signed receipt anyone can verify offline; body SHA-256 to match against their logs; token stored hashed; expiry and revoke |
| **Dashboard** | Overview with success rate and latency, endpoint health, event and delivery explorer, audit log | Light and dark themes; plain-English explanations of failures |
| **SDKs** | Python and Node packages to send events and verify signatures | Tested offline |
| **Retention** | Old events deleted after 30 days, audit logs after 365 | Only once nothing about them is still in progress |
| **Monitoring** | Prometheus `/metrics`, health checks, alerts when the queue backs up or workers go quiet | The health check reports database, Redis and worker separately |

## 9. Data model (main tables)

```
users ─┬─< account_members (team: user, role)
       ├─< api_keys (hashed, scopes)
       ├─< consumers (customer portal)
       ├─< endpoints ─< endpoint_subscriptions (event type patterns)
       │      secret (encrypted), retry settings, failure counters, security_check (JSONB)
       └─< events (payload JSONB) ─< deliveries ─< delivery_attempts
                                        │    status, attempt_count, next_attempt_at, locked_until (lease)
                                        ├─< delivery_replays
                                        └─< proof_links (token hash, expiry)
outbox_messages, idempotency_keys, audit_logs, user_sessions, email_codes
```

- **IDs** are prefixed and time-sortable (ULID style, `evt_01JD8…`). The prefix shows what kind of object an ID
  is, and sorting by ID sorts by time, which makes cursor pagination simple.
- **Delivery status values:** `pending` → `processing` → `delivered`, or `retrying` → … → `failed`, or
  `cancelled`.

## 10. Frontend

- **Next.js App Router:** a public site (landing page, platform page, contact, legal) and the dashboard.
- **One domain:** `/api/*` is rewritten to the backend, so the session cookie is first-party.
- **Middleware:** sends logged-out visitors to `/login`. The real check is the API answering 401.
- **Back button:** auth navigations use `location.replace`, and a "fresh on back" check stops Back showing the
  login page after logging in.
- **Theme:**
  - CSS variables, with dark mode from `prefers-color-scheme` plus a manual light/dark/system switch saved in
    `localStorage`;
  - a tiny inline script sets the theme before the page paints, so there's no flash.
- **Small reusable components:** status pills, confirm buttons, copy buttons and skeleton loaders.
- **Framing rules:** only `/portal` may be embedded in an iframe. Every other page sends
  `X-Frame-Options: DENY`, which prevents clickjacking.

## 11. Deployment

- **Vercel:** builds the dashboard on every push to `main`.
- **Render:** runs one Docker container. `start.sh` does three things:
  - runs `alembic upgrade head` (migrations);
  - starts the Celery worker with beat built in;
  - starts uvicorn.

  If either process dies, the container exits so Render restarts it. One container because Render's free plan
  gives one service. In production you'd split API, workers and beat.
- **Postgres and Redis:** managed services on Render.
- **Secrets** (encryption key, email credentials) live only in Render's environment, never in git.
- **GitHub Actions:** runs the tests on every push, and a scheduled job pings the API so the free instance doesn't
  sleep.

## 12. Testing

- **246 backend tests** (pytest) against a real Postgres and Redis (a separate test database), not mocks.
- **Outgoing HTTP** is mocked with **respx**, so tests control what the "receiver" answers.
- **What they cover:**
  - auth, API keys, scopes, roles and **tenant isolation on every route**;
  - ingestion limits and idempotency, **including concurrent identical requests**;
  - retries and backoff, timeouts, redirects, max attempts;
  - **the claim and lease logic, crash recovery, and the outbox with Redis down**;
  - SSRF and DNS rebinding;
  - signatures, including against the official Standard Webhooks library;
  - alerts, the security check, the portal (isolation between consumers), and proof links (receipts verify, and
    edits are detected).
- **Load test** (`loadtest/ingest.py`): about 150–180 events per second on a laptop, with a p50 of 7 ms for a
  single client.
- **Manual checks:** headless Chrome screenshots and click tests for UI changes.

## 13. Trade-offs and what I'd do next

**Trade-offs made on purpose:**
- **At-least-once, not exactly-once.** Exactly-once over HTTP isn't possible. Stable event IDs let receivers
  de-duplicate.
- **Polling the outbox every second** adds up to a second of delay when the immediate publish fails. It's simpler
  and more robust than change-data-capture.
- **Rate limiters fail open.** If Redis is down, accepting events is better than rejecting everything.
- **Fixed-window rate limits** are simpler than sliding windows and slightly less precise at window edges.
- **One container on Render** because it's free. It works, but you'd split it to scale workers separately.
- **Postgres as the delivery state store** caps throughput at what one database can handle. That's fine at this
  scale, and you'd partition or shard later.

**Next steps I'd take:**
- **Endpoint doctor:** plain-English diagnosis of why an endpoint fails (expired certificate, slow server, moved
  URL).
- **Gentle catch-up** after an outage, plus a per-endpoint requests-per-second limit.
- **Payload change warnings** when an event's shape changes.
- **Scaling:** separate worker pools, table partitioning by time, and a public status page.

## 14. Questions you'll likely be asked

**"Why not just send the webhook directly from the API request?"**
Because the receiver might be slow or down. The customer's request would hang, and a failure would lose the event.
Accepting fast (202) and delivering in the background decouples the two, and makes retries possible.

**"What happens if Redis goes down?"**
Events are still accepted, because they're saved in Postgres with their outbox messages. When Redis comes back,
the outbox publisher and the sweeper re-queue everything due. Nothing is lost, it's only delayed.

**"What if a worker crashes mid-delivery?"**
The delivery is `processing` with a 60-second lease. When the lease expires, the sweeper puts it back. It might be
sent twice, which is why delivery is at-least-once and event IDs are stable.

**"How do you stop two workers sending the same delivery?"**
Claiming is one atomic `UPDATE … WHERE status IN ('pending','retrying') AND next_attempt_at <= now()` that also
sets the lease. Only one worker's update matches the row, and the other gets nothing.

**"How does the receiver know the webhook is really from you?"**
An HMAC-SHA256 signature over the timestamp and body, with a secret only we and they know. They recompute and
compare in constant time, and reject old timestamps to stop replays.

**"What's SSRF and how did you prevent it?"**
Server-side request forgery: tricking the server into calling internal addresses. I check URLs when they're saved,
and when sending I resolve DNS myself, reject private IPs, and connect to the exact IP I checked, which stops DNS
rebinding. Redirects aren't followed.

**"How do you store secrets and passwords?"**
- **Passwords:** Argon2 hashes.
- **API keys and session tokens:** SHA-256 hashes, because we only need to compare them.
- **Endpoint signing secrets:** encrypted with Fernet, because we need the original to sign each request.

**"How is one customer's data kept from another's?"**
Every query filters by account ID, taken from the authenticated session or key, never from the request body. Tests
check every route returns 404 for another account's IDs.

**"Why Postgres and not MongoDB?"**
The delivery engine depends on transactions (the outbox) and row-level locking (claims and idempotency). JSONB
still gives flexible payload storage.

**"Why Celery?"**
It gives worker processes, task routing and a scheduler (beat) for the periodic jobs. The design doesn't depend
on Celery's own reliability, because Postgres holds the truth.

**"How would you scale it?"**
- Run more workers (they coordinate through atomic claims) and more API processes (they're stateless).
- Then partition the events, deliveries and attempts tables by time, use read replicas for the dashboard, and
  eventually shard by account.

**"What was the hardest bug?"**
Pick one you remember. Good candidates from the work log:
- the sweeper's `SELECT … FOR UPDATE` failing because of an automatic outer join (fixed by locking only the
  deliveries table);
- the demo data showing replays succeeding while the endpoint was still broken (fixed by checking the endpoint's
  behaviour at replay time).

**"What would you do differently?"**
Split API and workers into separate services from day one, and add tracing (OpenTelemetry) to follow one event
across the API, queue and worker.

## 15. Where things are in the code

| What | Where |
|---|---|
| API routes | `backend/app/routers/` (`events.py`, `endpoints.py`, `deliveries.py`, `auth.py`, `portal.py`, `proofs.py`…) |
| Delivery engine (claim, send, record, sweep) | `backend/app/worker/engine.py` |
| Retry timing | `backend/app/worker/retry.py` |
| Outbox | `backend/app/outbox.py` |
| SSRF guard | `backend/app/urlguard.py` |
| Signing | `backend/app/signing.py` |
| Permissions and roles | `backend/app/permissions.py`, `backend/app/deps.py` |
| Database models and migrations | `backend/app/models.py`, `backend/alembic/versions/` |
| Settings | `backend/app/config.py` |
| Tests | `backend/tests/` |
| Dashboard pages | `frontend/app/(dash)/` |
| API client | `frontend/lib/api.ts` |
| More detail | `docs/api.md`, `docs/signatures.md`, `docs/operations.md`, `docs/PRD.md`, `WORKLOG.md` |
