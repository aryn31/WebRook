# HookFlow API (v1)

Base path: `/v1`. All bodies are JSON. All timestamps are ISO-8601 UTC strings.

## Authentication

Two ways to authenticate:

| Method | How | Used by |
| --- | --- | --- |
| Session cookie | `hf_session` HttpOnly cookie, set by `/v1/auth/login` or `/v1/auth/register` | Dashboard |
| API key | `Authorization: Bearer hf_<prefix>_<secret>` | Your application |

Routes marked **session only** reject API keys. All other routes accept either.

Every resource belongs to one account. Asking for another account's resource returns `404`.

### Permissions

Each route needs one permission. A dashboard user has the permissions of their [role](#team-session-only) in the
account they're working in. An API key has only the **scopes** it was created with.

| Permission | Allows | Owner | Admin | Developer | Viewer |
| --- | --- | :-: | :-: | :-: | :-: |
| `events:write` | `POST /v1/events` | ✓ | ✓ | ✓ | |
| `events:read` | Read events, `GET /v1/stats`, `GET /v1/usage` | ✓ | ✓ | ✓ | ✓ |
| `deliveries:read` | Read deliveries, attempts and replays | ✓ | ✓ | ✓ | ✓ |
| `deliveries:replay` | Replay deliveries: one, per event, or in bulk | ✓ | ✓ | ✓ | |
| `endpoints:read` | Read endpoints (not their secrets) | ✓ | ✓ | ✓ | ✓ |
| `endpoints:write` | Create, change, delete endpoints; view and rotate secrets | ✓ | ✓ | ✓ | |
| `audit:read` | `GET /v1/audit-logs` | ✓ | ✓ | ✓ | ✓ |
| `api_keys:manage` | Create and revoke API keys (session only) | ✓ | ✓ | ✓ | |
| `team:manage` | Invite, remove and change members (session only) | ✓ | ✓ | | |

Missing a permission returns `403`: `insufficient_scope` for an API key (`details.required_scope` names it), or
`forbidden` for a dashboard user.

## Errors

Every error has the same shape:

```json
{ "error": { "code": "not_found", "message": "Endpoint not found.", "details": null } }
```

Common codes: `unauthorized` (401), `forbidden` / `insufficient_scope` (403), `not_found` (404), `conflict` / `email_taken` (409),
`idempotency_key_reused` (409), `not_replayable` / `nothing_to_replay` (409),
`validation_error` (422, `details` holds field errors), `payload_too_large` (413), `rate_limited` and
`quota_exceeded` (429, with a `Retry-After` header), `service_unavailable` (503, a temporary database outage: retry
after the `Retry-After` seconds).

## Pagination

List endpoints take `limit` (1–100, default 25) and `cursor`. They return:

```json
{ "data": [ ... ], "next_cursor": "evt_01J..." }
```

`next_cursor` is `null` on the last page. Pass it back as `cursor` to get the next page. Newest first.

---

## Auth (session only)

### `POST /v1/auth/register`
Body: `{ "email": "a@b.com", "password": "at least 10 chars" }`
`201` → `{ "user": User }` and sets the session cookie. `409 email_taken`.

### `POST /v1/auth/login`
Body: `{ "email", "password" }` → `200 { "user": User }` and sets the cookie.
`401 invalid_credentials`. `429 rate_limited` after too many attempts.

### `POST /v1/auth/logout` → `204`, session invalidated and cookie cleared.

### `GET /v1/auth/me` → `200 Me` or `401`.

```ts
type User = { id: string; email: string; created_at: string }
type Account = { id: string; owner_email: string; role: "owner" | "admin" | "developer" | "viewer"; personal: boolean }
type Me = {
  user: User;               // who is logged in
  account: Account;         // the account this session is working in
  permissions: string[];    // what the role allows there
  accounts: Account[]       // every account the user can switch to (their own first)
}
```

### `POST /v1/auth/switch-account`
Body: `{ "account_id": "usr_..." }` → `200 Me`. Work in another account (your own, or a team you belong to). Applies
to this session only. `404` if you're not a member.

### Email verification

New accounts get a 6-digit code by email. Until it's entered, every other route answers
`403 email_unverified`, except `GET /v1/auth/me`, `POST /v1/auth/logout` and the two below. `User` objects include
`email_verified`. `POST /v1/auth/register` also returns `verification_email_sent` (false if sending failed). Signing
up with the email of an account that was never verified replaces that account; a verified email returns
`409 email_taken`.

### `POST /v1/auth/verify-email`
Body: `{ "code": "123456" }` → `200 { "user": User }`. `400 invalid_code` (with `details.attempts_left`) or
`400 code_expired`: after 15 minutes or 5 wrong guesses, request a new code.

### `POST /v1/auth/resend-verification` → `200 { "sent_to", "resend_after_seconds" }`
Emails a new code; the previous one stops working. `429 resend_too_soon` within 60 seconds of the last code (with
`Retry-After`), at most 5 per hour, `503 email_failed` if sending failed, `400 already_verified`.

### `POST /v1/endpoints/{id}/security-check` (endpoints:write)
Checks whether the endpoint verifies signatures. Sends five test requests at once (event type
`hookflow.security_check`, header `HookFlow-Security-Check: <probe>`): `valid` (should be accepted), and
`wrong_signature`, `tampered_body`, `old_timestamp` (an hour old) and `missing_signature` (all should be rejected).
Any non-2xx answer counts as rejected. Returns the endpoint with `security_check`:
`{ verdict, summary, checked_at, probes: [{ name, label, expected, status_code, error, accepted, ok, server_error }] }`.
Verdicts: `pass`, `partial` (signature checked but old requests accepted), `fail` (forged requests accepted),
`inconclusive` (the genuine request wasn't accepted, or some requests got no answer). Saved on the endpoint and
cleared when its URL changes. 6 per minute per endpoint. Audit action `endpoint.security_checked`.

### `POST /v1/contact`
The website's contact form; no login needed. Body: `{ "name", "email", "topic", "message", "website" }` →
`202 { "message" }`. `topic` is `question`, `support`, `sales`, `bug` or `other`; `message` is 10–5000 characters;
`website` is a hidden field that must stay empty (anything in it drops the message quietly). Emailed to
`SUPPORT_EMAIL` with Reply-To set to the sender. 5 messages an hour per IP and per email (`429 rate_limited`);
`503 email_failed` if it couldn't be sent (the message names the support address).

### Forgot password

No login needed. Codes work like verification codes: 6 digits, 15 minutes, 5 wrong guesses.

### `POST /v1/auth/forgot-password`
Body: `{ "email" }` → `202 { "message", "resend_after_seconds" }`. Emails a reset code if the account exists. The
answer is the same either way, so it can't be used to find accounts; requests within 60 seconds of the last code,
or over 5 an hour, are skipped without an error.

### `POST /v1/auth/reset-password`
Body: `{ "email", "code", "new_password" }` (new: 10–256 characters) → `200 { "user": User }`. Sets the new
password, signs out every session, logs this browser in (sets the session cookie) and marks the email verified.
`400 invalid_code` (with `details.attempts_left`) or `400 code_expired`.

### Password and sessions

These act on the logged-in person, whichever account they're working in, and are recorded in that person's own
audit log.

### `PATCH /v1/auth/preferences`
Body: `{ "failure_alerts": bool }` → `200 { "user": User }`. Your email settings, for every account you belong to.
`failure_alerts` (default on): email me when an endpoint in an account I own or administer fails
`ALERT_AFTER_FAILURES` attempts in a row (default 5), and once more when it next succeeds. `User` includes
`failure_alerts`; endpoints include `alert_sent_at` (when the failing email went out, null when not failing).

### `POST /v1/auth/password`
Body: `{ "current_password", "new_password" }` (new: 10–256 characters) → `200 { "signed_out_sessions": n }`.
Every other session is signed out, and this session gets a new cookie, so a copied old token stops working.
`400 invalid_current_password` or `400 same_password`. Rate limited like login.

### `GET /v1/auth/sessions` → `{ "data": Session[] }`
Sessions that haven't expired or been signed out, most recently used first:
`{ "id", "created_at", "last_seen_at", "expires_at", "ip_address", "user_agent", "current" }`. `last_seen_at` and
`ip_address` are updated at most every 5 minutes.

### `DELETE /v1/auth/sessions/{id}` → `204`
Sign out one of your sessions. Signing out the current one also clears the cookie. `404` if it isn't yours or is
already signed out.

### `POST /v1/auth/sessions/sign-out-others` → `200 { "signed_out_sessions": n }`

## Team (session only)

An account is named after its owner. The owner can invite people to work in it. Each member has a role:

- **Owner**: the user whose account it is. Can't be removed or changed. The only one who can manage admins.
- **Admin**: everything, including inviting and removing members (but not other admins).
- **Developer**: everything except managing the team.
- **Viewer**: read only. Can't see signing secrets.

Members see the account's data after switching into it. API keys and endpoints belong to the account, not to the
person who made them, so they keep working when that person leaves.

### `GET /v1/team/members` → `{ "data": Member[] }` (owner first). Any member can read it.
```ts
type Member = { user_id: string; email: string; role: "owner" | "admin" | "developer" | "viewer"; joined_at: string }
```
### `PATCH /v1/team/members/{user_id}`
Body: `{ "role": "admin" | "developer" | "viewer" }` → `Member`. Needs `team:manage`.
### `DELETE /v1/team/members/{user_id}` → `204`
Needs `team:manage`, except to remove yourself (leave). The removed person's sessions go back to their own account.
### `GET /v1/team/invites` → `{ "data": Invite[] }` (open invites only)
### `POST /v1/team/invites`
Body: `{ "email": "dev@example.com", "role": "developer" }` (default role `developer`)
`201` → `{ "invite": Invite, "token": "hfinv_...", "accept_path": "/invite/hfinv_..." }`. **The token is only
returned here.** HookFlow doesn't send email: share the link (dashboard URL + `accept_path`) yourself. Invites
expire after 7 days. Inviting the same email again replaces the old link. `409 already_member`.
### `DELETE /v1/team/invites/{id}` → `Invite` (revoked)
### `GET /v1/invites/{token}` → `{ "account_owner_email", "email", "role", "expires_at" }`
### `POST /v1/invites/{token}/accept` → `200 { "user": User }`
The logged-in user's email must match the invite (`403 invite_wrong_user`). Joins the account and switches this
session into it. An invalid, expired or used link returns `404 invite_invalid`.

```ts
type Invite = { id: string; email: string; role: string; created_at: string; expires_at: string;
                accepted_at: string | null; revoked_at: string | null }
```

## API keys (session only)

### `GET /v1/api-keys` → `{ "data": ApiKey[] }` (includes revoked keys)

### `GET /v1/api-keys/scopes` → `{ "data": { "scope", "description" }[] }`

### `POST /v1/api-keys`
Body: `{ "name": "Production", "scopes"?: ["events:write"] }`
`201` → `{ "api_key": ApiKey, "key": "hf_ab12cd34_..." }`. **`key` is only ever returned here.**

`scopes` defaults to every [scope](#permissions) your role allows. You can't give a key more than your role has
(`403 forbidden`). A key for a production server usually needs only `events:write`. Scopes can't be changed later:
create a new key instead.

### `DELETE /v1/api-keys/{id}` → `200 { "api_key": ApiKey }` (revoked; revoking twice is a no-op)

```ts
type ApiKey = {
  id: string; name: string; prefix: string;           // prefix like "hf_ab12cd34", safe to display
  scopes: string[];                                    // keys made before scopes existed have all of them
  created_by_user_id: string | null;
  created_at: string; last_used_at: string | null; revoked_at: string | null
}
```

## Endpoints

```ts
type Endpoint = {
  id: string; url: string; description: string | null; enabled: boolean;
  event_types: string[];        // event types, patterns like "order.*", or ["*"] for all events
  max_attempts: number;         // attempts per delivery, including the first (1–10, default 5)
  retry_schedule: number[] | null;  // seconds before each retry; null = default backoff
  previous_secret_expires_at: string | null;  // set while a rotation grace period is running
  created_at: string; updated_at: string
}
```

### `GET /v1/endpoints` → paginated `Endpoint[]`, each with `health`
`health` covers delivery attempts in the last 24 hours (also returned by `GET /v1/endpoints/{id}`):

```ts
type EndpointHealth = {
  state: "idle" | "healthy" | "degraded" | "failing"; // idle: no attempts; healthy: 95%+ succeeded;
                                                      // failing: last attempt failed and under half succeeded
  attempts: number; successes: number; success_rate: number | null;  // 0-1
  last_attempt_at: string | null; last_success: boolean | null;
  last_status_code: number | null; last_error: string | null
}
```

### `POST /v1/endpoints`
Body: `{ "url": "https://example.com/hooks", "description"?: string, "event_types": ["order.created"], "enabled"?: true, "max_attempts"?: 5, "retry_schedule"?: [30, 300, 1800] }`
`201` → `Endpoint & { "signing_secret": "whsec_..." }`

**Event types and patterns.** Each entry in `event_types` is one of:

| Entry | Matches |
| --- | --- |
| `order.created` | exactly `order.created` |
| `order.*` | every type starting with `order.`: `order.created`, `order.item.added`, … (not `order` or `orders.x`) |
| `*` | every event |

`*` is only allowed on its own or at the end after a dot. An event matching several entries is delivered once.

**Retry schedule.** By default retries back off exponentially (about 30s, 2m, 8m, 32m, up to 6h). Set
`retry_schedule` to choose the waits yourself: `[30, 300, 1800]` waits 30s after the first failed attempt, 5m after
the second, then 30m before every later retry. 1–9 values, each from 1 second to 24 hours. The waits get ±10%
jitter, and a longer `Retry-After` from your server still wins. `max_attempts` still sets how many attempts there are.
### `GET /v1/endpoints/{id}` → `Endpoint & { health: EndpointHealth }`
### `PATCH /v1/endpoints/{id}`
Body: any of `url`, `description`, `event_types`, `enabled`, `max_attempts`, `retry_schedule` → `Endpoint`.
A new `max_attempts` applies to deliveries created afterwards; existing ones keep the limit they started with.
A new `retry_schedule` applies from the next retry, including deliveries already retrying. Send `null` to go back
to the default backoff.
### `DELETE /v1/endpoints/{id}` → `204`
Archives the endpoint: it disappears from lists, gets no new deliveries, and its unsent deliveries are cancelled. Delivery history stays.
### `GET /v1/endpoints/{id}/secret` → `{ "signing_secret": "whsec_...", "previous_secret_expires_at": string | null }`
Each call is recorded in the audit log.
### `POST /v1/endpoints/{id}/rotate-secret`
Body (optional): `{ "grace_period_seconds": 86400 }` (0 to 604800, default 24 hours)
→ `{ "signing_secret": "whsec_<new>", "previous_secret_expires_at": "..." | null }`

During the grace period every request carries two signatures, one per secret:
`HookFlow-Signature: v1=<new>,v1=<old>`. Your receiver can switch to the new secret at any point in that window
without rejecting anything. With `grace_period_seconds: 0` the old secret stops at once. Rotating again during a
grace period replaces the old secret with the one being rotated out.

## Customer portal

For SaaS apps that send webhooks to their own customers. A **consumer** is one of your customers. Each gets a
portal (a page you embed in your app) where they manage their own endpoints. They can never see your other
consumers, your own endpoints or anything else in your account.

### Consumers (endpoints:read to list and read, endpoints:write to change)

- `POST /v1/consumers`: body `{ "uid", "name"? }`, returns `201 Consumer`. `uid` is your ID for them (letters,
  digits and `. _ : @ -`, up to 100 characters), unique in your account; `409 consumer_exists` otherwise.
- `GET /v1/consumers`: paginated.
- `GET /v1/consumers/{ref}`: `ref` is the uid or the `cns_…` ID.
- `PATCH /v1/consumers/{ref}`: body `{ "name" }`.
- `DELETE /v1/consumers/{ref}`: deletes the consumer, deletes their endpoints and cancels anything not yet sent.
  Open portal links stop working.

`Consumer`: `{ id, uid, name, endpoint_count, created_at }`.

### Sending to a consumer

Add `"consumer": "<uid or ID>"` to `POST /v1/events`. The event goes only to that consumer's endpoints.

- Events without `consumer` go only to your own endpoints, never to consumers'.
- An unknown consumer gives `422 unknown_consumer`.
- Events show `consumer_id`.
- `GET /v1/endpoints` lists your own endpoints. Add `?consumer=<ref>` to list a consumer's instead.
- Consumers' endpoints don't send you failure alerts.
- Each consumer can have up to `MAX_ENDPOINTS_PER_CONSUMER` endpoints (default 10); this doesn't count toward
  your account's limit.

### `POST /v1/consumers/{ref}/portal` (endpoints:write)

Body `{ "brand_name"?, "ttl_minutes"? }` (5–1440, default `PORTAL_LINK_TTL_MINUTES` = 60), returns
`{ url, token, expires_at }`.

- Create a link when the consumer opens the webhooks page in your app, then show `url` in an iframe or open it.
- Anyone with the link can manage that consumer's endpoints until it expires, so don't store it or send it by
  email.
- The token is signed, not stored, and sits in the URL fragment, which browsers don't send to servers.
- `brand_name` is shown at the top of the portal ("ShopCo webhooks").
- The `/portal` page may be framed by any site; every other dashboard page refuses to be framed.

### Portal API

What the portal page calls, with `Authorization: Bearer hfp_…` (the portal token). It's limited to that one
consumer and 120 requests per minute. A portal token doesn't work on any other route. An expired or forged token
gives `401 portal_link_expired` or `portal_link_invalid`.

| Route | Does |
| --- | --- |
| `GET /v1/portal/me` | The consumer, brand name, expiry, and event types sent recently (to pick from) |
| `GET /v1/portal/endpoints` | Their endpoints, with health |
| `POST /v1/portal/endpoints` | Add one: `{ url, description?, event_types? }` (default all); returns the signing secret |
| `GET` / `PATCH` / `DELETE /v1/portal/endpoints/{id}` | Read; change `url`, `description`, `event_types`, `enabled`; delete |
| `GET /v1/portal/endpoints/{id}/secret` | The signing secret |
| `POST /v1/portal/endpoints/{id}/security-check` | The signature check |
| `GET /v1/portal/endpoints/{id}/deliveries` | Recent deliveries to it, paginated |
| `GET /v1/portal/deliveries/{id}/attempts` | A delivery's attempts |
| `POST /v1/portal/deliveries/{id}/replay` | Replay a failed or cancelled delivery |

Portal actions are recorded in your audit log with actor type `portal` and `details.consumer`. Audit actions:
`consumer.created`, `consumer.updated`, `consumer.deleted`, `consumer.portal_opened`.

## Events

### `POST /v1/events`
Body: `{ "event_type": "order.created", "data": { ...any JSON object... } }`
- `event_type`: 1–100 chars, letters/digits/`_`/`-` in dot-separated parts (`order.created`).
- Body limit 1 MiB → `413 payload_too_large`.

**Limits.** Each account can send 600 events per minute and 10,000 new events per UTC day by default. Every response
reports where you stand:

| Header | Meaning |
| --- | --- |
| `X-RateLimit-Limit`, `X-RateLimit-Remaining` | Requests allowed per minute, and left in this minute |
| `X-RateLimit-Reset` | Seconds until the minute resets |
| `X-Quota-Limit`, `X-Quota-Remaining` | New events allowed per day, and left today |
| `X-Quota-Reset` | Seconds until midnight UTC |

Over the per-minute limit → `429 rate_limited`; over the daily quota → `429 quota_exceeded`. Both carry
`Retry-After`. Every request counts toward the per-minute limit. Only requests that create an event use quota, so an
idempotent retry (below) doesn't. Operators can change the defaults (`EVENT_RATE_LIMIT_PER_MINUTE`,
`DAILY_EVENT_QUOTA`) or set either per account in the `users` table; `0` means unlimited.

`202` →
```json
{ "event_id": "evt_01J...", "status": "accepted", "created_at": "...", "delivery_count": 2 }
```
Returned only after the event and its deliveries are saved. HookFlow does not wait for your endpoints.

**Idempotency.** Send an `Idempotency-Key` header (1–255 printable ASCII characters, no spaces) to make retries safe:

```bash
curl -X POST localhost:8000/v1/events -H "Authorization: Bearer $HOOKFLOW_KEY" \
  -H "Idempotency-Key: order-ORD-101-created" -H "Content-Type: application/json" \
  -d '{"event_type":"order.created","data":{"order_id":"ORD-101"}}'
```

- Same key and same request: returns the original `202` response with the same `event_id` and the header
  `Idempotent-Replayed: true`. No new event, nothing sent again.
- Same key, different `event_type` or `data`: `409 idempotency_key_reused`, with the original `event_id` in `details`.
  "Same" compares JSON values, so key order and whitespace don't matter.
- Keys are per account and remembered for 24 hours. After that the key can be used again.
- Two requests racing with the same new key still create only one event.

### `GET /v1/events`
Query: `limit`, `cursor`, `event_type`, `created_after` (inclusive), `created_before` (exclusive) (ISO datetimes) → paginated `EventSummary[]`

```ts
type DeliveryCounts = { total: number; pending: number; processing: number; retrying: number;
                        delivered: number; failed: number; cancelled: number }
type EventSummary = { id: string; event_type: string; created_at: string; deliveries: DeliveryCounts }
type Event = EventSummary & { data: Record<string, unknown>; idempotency_key: string | null }
```

### `GET /v1/events/{id}` → `Event`
### `GET /v1/events/{id}/deliveries` → `{ "data": Delivery[] }`
### `POST /v1/events/{id}/replay`
Body (optional): `{ "endpoint_ids": ["ep_..."] }` to replay only deliveries to those endpoints.
Replays every failed or cancelled delivery of the event (see [Replay](#replay)). Never creates a new event or new
deliveries, even for endpoints added after the event was sent.
`202` → `{ "replayed": { "replay": Replay, "delivery": Delivery }[], "skipped": { "delivery_id", "reason" }[] }`
`409 nothing_to_replay` if none can be replayed (`details` lists the reasons).

## Deliveries

One delivery = one event going to one endpoint.

```ts
type DeliveryStatus = "pending" | "processing" | "retrying" | "delivered" | "failed" | "cancelled"
type Delivery = {
  id: string; event_id: string; event_type: string;
  endpoint_id: string; endpoint_url: string;
  status: DeliveryStatus;
  attempt_count: number; max_attempts: number;   // totals; both grow with each manual replay
  run_attempt_count: number; run_max_attempts: number;  // counted from the last replay (or creation)
  next_attempt_at: string | null;        // set while pending/retrying
  last_status_code: number | null;
  last_error: string | null;             // human readable, e.g. "Destination returned HTTP 503"
  delivered_at: string | null;
  replay_count: number; last_replayed_at: string | null;
  replayable: boolean;                   // true when POST .../replay would be accepted right now
  created_at: string; updated_at: string
}
type Attempt = {
  id: string; attempt_number: number;
  started_at: string; completed_at: string | null; duration_ms: number | null;
  response_status: number | null;
  response_body: string | null;          // first 4 KiB only
  error: string | null; success: boolean
}
```

### `GET /v1/deliveries`
Query: `limit`, `cursor`, `status`, `endpoint_id`, `event_id` → paginated `Delivery[]`
### `GET /v1/deliveries/{id}` → `Delivery`
### `GET /v1/deliveries/{id}/attempts` → `{ "data": Attempt[] }` (oldest first)
### `POST /v1/deliveries/{id}/replay` → `202 { "replay": Replay, "delivery": Delivery }`
### `GET /v1/deliveries/{id}/replays` → `{ "data": Replay[] }` (oldest first)
### `POST /v1/deliveries/replay` (bulk replay)
Replays many failed deliveries at once, oldest first. Body (all optional):

```json
{ "endpoint_id": "ep_...", "event_type": "order.created", "statuses": ["failed"],
  "created_after": "2026-11-01T00:00:00Z", "created_before": "2026-11-02T00:00:00Z",
  "limit": 100, "dry_run": false }
```

- `statuses`: `failed` and/or `cancelled` (default `["failed"]`). `limit`: 1–500 (default 100).
- Only deliveries to enabled endpoints are matched.
- `dry_run: true` reports what would be replayed and changes nothing.
- Rate limited to 10 requests per minute per account (separate from the single-replay limit).

`200` → `{ "matched": 100, "replayed": ["dlv_..."], "skipped": [{ "delivery_id", "reason" }], "has_more": true, "dry_run": false }`

Replayed deliveries leave the `failed` state, so while `has_more` is `true`, send the same request again to replay
the next batch. Each bulk replay writes one `deliveries.bulk_replayed` audit entry, plus one `delivery.replayed`
per delivery.

```ts
type Replay = {
  id: string; delivery_id: string;
  previous_status: "failed" | "cancelled";
  first_attempt_number: number;   // attempts numbered from here on belong to this replay
  requested_by: { type: "session" | "api_key"; api_key_id: string | null };
  created_at: string
}
```

### Replay

A replay sends the **same** event to the same endpoint again: same event ID, same delivery ID, same body. Earlier
attempts stay in the history, and new attempts continue the numbering (`HookFlow-Attempt: 2`, `3`, …).

- Only `failed` and `cancelled` deliveries can be replayed. Anything else returns `409 not_replayable`. Once
  replayed, a delivery is `pending` again, so repeating the request can't queue it twice.
- The endpoint must be enabled and not deleted, and its current URL must pass today's URL rules. The current URL and
  signing secret are used, so you can fix a wrong URL and then replay.
- A replay gets a fresh retry budget: the endpoint's `max_attempts`, with the normal backoff (about 30s, 2m, …).
- Replays are rate limited to 60 deliveries per minute per account. Replaying an event with 5 failed deliveries uses 5.
- Every replay is recorded in `GET /v1/deliveries/{id}/replays` and in the audit log.

## Stats

### `GET /v1/stats?range=24h|7d|30d` (default `7d`)
```ts
type Stats = {
  range: "24h" | "7d" | "30d";
  events_total: number;                       // events created in range
  deliveries_total: number;                   // deliveries created in range
  deliveries_by_status: Omit<DeliveryCounts, "total">;
  latency_ms: { p50: number; p95: number } | null;
  series: { bucket: string; events: number; delivered: number; failed: number }[]  // hourly for 24h, daily otherwise
}
```

`latency_ms` is `{ "p50": number, "p95": number }`: how long endpoints took to respond to attempts in the range, or
`null` when there were none.

## Usage

### `GET /v1/usage`
Where the account stands against its [ingestion limits](#post-v1events). Reading it doesn't count toward them.

```json
{
  "events_today":         { "limit": 10000, "used": 1240, "remaining": 8760, "resets_in_seconds": 22140 },
  "requests_this_minute": { "limit": 600,   "used": 3,    "remaining": 597,  "resets_in_seconds": 41 }
}
```
`limit` and `remaining` are `null` when the account is unlimited.

## Audit log

### `GET /v1/audit-logs`
Query: `limit`, `cursor`, `action`, `resource_id` → paginated `AuditLog[]`

```ts
type AuditLog = {
  id: string; action: string;
  actor: {
    type: "session" | "api_key"; api_key_id: string | null;
    user_id: string | null; email: string | null   // the person: logged-in user, or the key's creator
  };
  resource_type: string | null; resource_id: string | null;
  details: Record<string, unknown> | null;   // never contains secrets or keys
  ip_address: string | null; created_at: string
}
```

| Action | When |
| --- | --- |
| `auth.registered`, `auth.login` | Account created, signed in |
| `auth.email_verified` | Email address verified |
| `auth.password_reset` | Password reset with an emailed code; `details.signed_out_sessions` |
| `auth.preferences_changed` | Email settings changed; `details.failure_alerts` |
| `auth.password_changed`, `auth.session_signed_out`, `auth.sessions_signed_out` | Password changed, sessions signed out from the Security page |
| `api_key.created`, `api_key.revoked` | API key changes |
| `endpoint.created`, `endpoint.archived` | |
| `endpoint.updated` | `details.changes` = `{ field: { from, to } }` |
| `endpoint.secret_viewed`, `endpoint.secret_rotated` | Signing secret read or rotated |
| `delivery.replayed`, `event.replayed` | Manual replays |
| `deliveries.bulk_replayed` | Bulk replay; `details` has the filters and count |
| `team.invite_created`, `team.invite_revoked` | Invitations |
| `team.member_joined`, `team.member_role_changed`, `team.member_removed`, `team.member_left` | Team changes |

## Health (no auth)

- `GET /health/live` → `200 { "status": "ok" }`
- `GET /health/ready` → `200` when Postgres and Redis are reachable, else `503`. The body also has `"worker"`:
  `ok`, `stale` (no scheduled task has run for 2 minutes) or `unknown`. A stale worker doesn't fail the check.
- `GET /metrics` → Prometheus metrics (see [operations.md](operations.md)). Needs `Authorization: Bearer
  <METRICS_TOKEN>` when that setting is set.

---

## Delivery behaviour

- Delivery is **at-least-once**. A crash after your server received a request but before HookFlow saved the result means
  the same event can arrive again. The `id` field and the `HookFlow-Event-Id` header stay the same across repeats, so use
  them to skip events you have already processed.
- Any 2xx response counts as success. Redirects are not followed.
- Timeout: 10 seconds per attempt.
- Retries: up to 5 attempts in total by default (the first try plus 4 retries); set `max_attempts` per endpoint
  (1–10). HookFlow retries on HTTP 408, 429 and 5xx, and on connection errors and timeouts. The waits grow
  exponentially with random jitter: about 30s, 2m, 8m, 32m, 2h (capped at 6h), or follow the endpoint's
  [`retry_schedule`](#post-v1endpoints). A `Retry-After` header is honoured.
  Other 4xx responses fail at once with no retry. Failed deliveries can be [replayed](#replay).
- Retry times are stored in Postgres, so they survive restarts. Nothing is sent before its scheduled time.
- At most 10 requests are in flight to one endpoint at a time (`ENDPOINT_MAX_CONCURRENCY`). Extra deliveries wait a
  couple of seconds without using up an attempt.
- Destinations must be public. HookFlow resolves the host when it connects and refuses private, loopback, link-local
  and reserved addresses. It connects to the exact address it checked, so a DNS change can't redirect a request
  inside your network. A failed DNS lookup is retried like a connection error.
- Events, with their deliveries and attempts, are kept for 30 days (`EVENT_RETENTION_DAYS`) and then deleted. An
  event with a delivery still in progress is kept until it finishes.

### Request sent to your endpoint

```http
POST /your/path
Content-Type: application/json
User-Agent: HookFlow/1.0
HookFlow-Event-Id: evt_01J...
HookFlow-Event-Type: order.created
HookFlow-Delivery-Id: dlv_01J...
HookFlow-Attempt: 1
HookFlow-Timestamp: 1793361600
HookFlow-Signature: v1=5f2b...        (two comma-separated values during a secret rotation grace period)

{"id":"evt_01J...","type":"order.created","created_at":"2026-10-30T12:00:00.000000Z","data":{...}}
```

### Verifying the signature

The [SDKs](../sdks) do this for you: `hookflow.verify(raw_body, headers, secret)` in Python and
`verify(rawBody, req.headers, secret)` in Node. To write it yourself:

`HookFlow-Signature` is `v1=` followed by the hex HMAC-SHA256 of `"{HookFlow-Timestamp}.{raw request body}"`,
keyed with your endpoint's full signing secret (including the `whsec_` prefix) as UTF-8 bytes.

1. Read the **raw** body bytes before any JSON parsing. Re-serializing the JSON changes the bytes and breaks the check.
2. Reject the request if the timestamp is more than 5 minutes from your clock. This stops old requests being replayed.
3. Compute the HMAC and compare it to each `v1=` value in the header using a constant-time comparison. Accept the
   request if any one matches. There are two values during a secret rotation grace period.

```python
import hmac, hashlib, time

def verify(secret: str, body: bytes, timestamp: str, signature_header: str, tolerance=300) -> bool:
    if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    parts = [p.strip() for p in signature_header.split(",")]
    candidates = [p[3:] for p in parts if p.startswith("v1=")]
    return any(hmac.compare_digest(expected, c) for c in candidates)
```

```js
import crypto from "node:crypto";

function verify(secret, rawBody, timestamp, signatureHeader, tolerance = 300) {
  if (!/^\d+$/.test(timestamp) || Math.abs(Date.now() / 1000 - Number(timestamp)) > tolerance) return false;
  const expected = Buffer.from(
    crypto.createHmac("sha256", secret).update(`${timestamp}.`).update(rawBody).digest("hex"),
  );
  return signatureHeader.split(",").some((part) => {
    part = part.trim();
    if (!part.startsWith("v1=")) return false;
    const sig = Buffer.from(part.slice(3));
    // Compare byte lengths first: timingSafeEqual throws on different lengths.
    return sig.length === expected.length && crypto.timingSafeEqual(sig, expected);
  });
}
```
