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

## Errors

Every error has the same shape:

```json
{ "error": { "code": "not_found", "message": "Endpoint not found.", "details": null } }
```

Common codes: `unauthorized` (401), `forbidden` (403), `not_found` (404), `conflict` / `email_taken` (409),
`idempotency_key_reused` (409), `not_replayable` / `nothing_to_replay` (409),
`validation_error` (422, `details` holds field errors), `payload_too_large` (413), `rate_limited` (429, with a
`Retry-After` header).

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

### `GET /v1/auth/me` → `200 { "user": User }` or `401`.

```ts
type User = { id: string; email: string; created_at: string }
```

## API keys (session only)

### `GET /v1/api-keys` → `{ "data": ApiKey[] }` (includes revoked keys)

### `POST /v1/api-keys`
Body: `{ "name": "Production" }`
`201` → `{ "api_key": ApiKey, "key": "hf_ab12cd34_..." }`. **`key` is only ever returned here.**

### `DELETE /v1/api-keys/{id}` → `200 { "api_key": ApiKey }` (revoked; revoking twice is a no-op)

```ts
type ApiKey = {
  id: string; name: string; prefix: string;           // prefix like "hf_ab12cd34", safe to display
  created_at: string; last_used_at: string | null; revoked_at: string | null
}
```

## Endpoints

```ts
type Endpoint = {
  id: string; url: string; description: string | null; enabled: boolean;
  event_types: string[];        // exact event types, or ["*"] for all events
  max_attempts: number;         // attempts per delivery, including the first (1–10, default 5)
  previous_secret_expires_at: string | null;  // set while a rotation grace period is running
  created_at: string; updated_at: string
}
```

### `GET /v1/endpoints` → paginated `Endpoint[]`
### `POST /v1/endpoints`
Body: `{ "url": "https://example.com/hooks", "description"?: string, "event_types": ["order.created"], "enabled"?: true, "max_attempts"?: 5 }`
`201` → `Endpoint & { "signing_secret": "whsec_..." }`
### `GET /v1/endpoints/{id}` → `Endpoint`
### `PATCH /v1/endpoints/{id}`
Body: any of `url`, `description`, `event_types`, `enabled`, `max_attempts` → `Endpoint`.
A new `max_attempts` applies to deliveries created afterwards; existing ones keep the limit they started with.
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

## Events

### `POST /v1/events`
Body: `{ "event_type": "order.created", "data": { ...any JSON object... } }`
- `event_type`: 1–100 chars, letters/digits/`_`/`-` in dot-separated parts (`order.created`).
- Body limit 1 MiB → `413 payload_too_large`.

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
Query: `limit`, `cursor`, `event_type`, `created_after`, `created_before` (ISO datetimes) → paginated `EventSummary[]`

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
  attempt_count: number; max_attempts: number;
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
  series: { bucket: string; events: number; delivered: number; failed: number }[]  // hourly for 24h, daily otherwise
}
```

## Audit log

### `GET /v1/audit-logs`
Query: `limit`, `cursor`, `action`, `resource_id` → paginated `AuditLog[]`

```ts
type AuditLog = {
  id: string; action: string;
  actor: { type: "session" | "api_key"; api_key_id: string | null };
  resource_type: string | null; resource_id: string | null;
  details: Record<string, unknown> | null;   // never contains secrets or keys
  ip_address: string | null; created_at: string
}
```

| Action | When |
| --- | --- |
| `auth.registered`, `auth.login` | Account created, signed in |
| `api_key.created`, `api_key.revoked` | API key changes |
| `endpoint.created`, `endpoint.archived` | |
| `endpoint.updated` | `details.changes` = `{ field: { from, to } }` |
| `endpoint.secret_viewed`, `endpoint.secret_rotated` | Signing secret read or rotated |
| `delivery.replayed`, `event.replayed` | Manual replays |

## Health (no auth)

- `GET /health/live` → `200 { "status": "ok" }`
- `GET /health/ready` → `200` when Postgres and Redis are reachable, else `503`.

---

## Delivery behaviour

- Delivery is **at-least-once**. A crash after your server received a request but before HookFlow saved the result means
  the same event can arrive again. The `id` field and the `HookFlow-Event-Id` header stay the same across repeats, so use
  them to skip events you have already processed.
- Any 2xx response counts as success. Redirects are not followed.
- Timeout: 10 seconds per attempt.
- Retries: up to 5 attempts in total by default (the first try plus 4 retries); set `max_attempts` per endpoint
  (1–10). HookFlow retries on HTTP 408, 429 and 5xx, and on connection errors and timeouts. The waits grow
  exponentially with random jitter: about 30s, 2m, 8m, 32m, 2h (capped at 6h). A `Retry-After` header is honoured.
  Other 4xx responses fail at once with no retry. Failed deliveries can be [replayed](#replay).
- Retry times are stored in Postgres, so they survive restarts. Nothing is sent before its scheduled time.

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

{"id":"evt_01J...","type":"order.created","created_at":"2026-10-30T12:00:00Z","data":{...}}
```

### Verifying the signature

`HookFlow-Signature` is `v1=` followed by the hex HMAC-SHA256 of `"{HookFlow-Timestamp}.{raw request body}"`,
keyed with your endpoint's full signing secret (including the `whsec_` prefix) as UTF-8 bytes.

1. Read the **raw** body bytes before any JSON parsing. Re-serializing the JSON changes the bytes and breaks the check.
2. Reject the request if the timestamp is more than 5 minutes from your clock. This stops old requests being replayed.
3. Compute the HMAC and compare it to each `v1=` value in the header using a constant-time comparison. Accept the
   request if any one matches. There are two values during a secret rotation grace period.

```python
import hmac, hashlib, time

def verify(secret: str, body: bytes, timestamp: str, signature_header: str, tolerance=300) -> bool:
    if abs(time.time() - int(timestamp)) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    candidates = [p.split("=", 1)[1] for p in signature_header.split(",") if p.startswith("v1=")]
    return any(hmac.compare_digest(expected, c) for c in candidates)
```

```js
import crypto from "node:crypto";

function verify(secret, rawBody, timestamp, signatureHeader, tolerance = 300) {
  if (Math.abs(Date.now() / 1000 - Number(timestamp)) > tolerance) return false;
  const expected = crypto.createHmac("sha256", secret).update(`${timestamp}.`).update(rawBody).digest("hex");
  return signatureHeader.split(",").some((part) => {
    const [v, sig] = part.split("=");
    return v === "v1" && sig.length === expected.length &&
      crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected));
  });
}
```
