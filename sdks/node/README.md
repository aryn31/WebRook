# hookflow (Node.js)

Official Node.js SDK for HookFlow. It verifies the webhooks HookFlow sends you and wraps the HookFlow API.
Node 18+, no runtime dependencies (it uses the global `fetch` and `node:crypto`). Ships ESM, CommonJS and
TypeScript types.

```bash
npm install hookflow                 # once published
npm install ./sdks/node              # from this repo (run `npm run build` in sdks/node first)
```

## Verify a webhook

```js
import { verify, WebhookVerificationError } from "hookflow";

const event = verify(rawBody, req.headers, "whsec_..."); // throws WebhookVerificationError
```

- **Pass the raw request body** as a `Buffer` or string. If you parse the JSON and serialize it again, the bytes
  change and the signature check fails. In Express, put `express.raw({ type: "application/json" })` on the webhook
  route, not `express.json()`.
- `headers` can be Node's `req.headers`, a Fetch `Headers` object, a `Map`, a plain object or an array of pairs.
  Header names are matched case-insensitively.
- `secret` is the endpoint's full signing secret, `whsec_` prefix included.
- Requests whose `HookFlow-Timestamp` is more than 300 seconds from your clock are rejected. Change the window
  with `verify(body, headers, secret, { toleranceSeconds: 600 })` (or pass the number on its own).
- While a secret rotation is in its grace period, `HookFlow-Signature` holds two signatures (`v1=<new>,v1=<old>`).
  The request is accepted if either one matches.
- On failure, `err.reason` is one of `missing_header`, `invalid_timestamp`, `timestamp_out_of_tolerance`,
  `no_signatures`, `signature_mismatch` or `invalid_payload`. Respond with 400.
- Delivery is at-least-once, so the same event can arrive twice. Use `event.id` (or the `HookFlow-Event-Id`
  header) to skip duplicates.

**Express**

```js
import express from "express";
import { verify, WebhookVerificationError } from "hookflow";

const app = express();

app.post("/webhooks/hookflow", express.raw({ type: "application/json" }), (req, res) => {
  let event;
  try {
    event = verify(req.body, req.headers, process.env.HOOKFLOW_WEBHOOK_SECRET); // req.body is a Buffer here
  } catch (err) {
    if (err instanceof WebhookVerificationError) return res.status(400).json({ error: err.reason });
    throw err;
  }
  handle(event.type, event.data);
  res.sendStatus(204);
});

app.use(express.json()); // other routes can still parse JSON
```

In a Fetch-style handler (Next.js route handlers, Hono, and so on), use
`verify(await request.text(), request.headers, secret)`.

`verifySignature(...)` runs the same checks without parsing the body. `sign(secret, timestamp, body)` produces a
valid `HookFlow-Signature` value for testing your handler.

## API client

```js
import { HookFlow } from "hookflow";

const hf = new HookFlow({ apiKey: "hf_ab12cd34_...", baseUrl: "https://hookflow.example.com" });
// or set HOOKFLOW_API_KEY / HOOKFLOW_BASE_URL and call new HookFlow()
```

Options: `timeout` (milliseconds per request, default 30000), `maxRetries` (default 2; see [Retries](#retries)) and
`fetch` (a custom fetch implementation).

Request parameters and response objects use the API's own field names (`event_type`, `endpoint_id`, `dry_run`,
...), exactly as in `docs/api.md`.

### Send an event

```js
const accepted = await hf.events.send(
  "order.created",
  { order_id: "ORD-101", total: 42.5 },
  { idempotencyKey: "order-ORD-101-created" }, // optional, but makes retries safe
);
accepted.event_id, accepted.delivery_count;
```

### Read events and deliveries

```js
const page = await hf.events.list({ event_type: "order.created", limit: 50 }); // one page
page.data, page.nextCursor, page.hasMore, await page.getNextPage();

for await (const event of hf.events.listAll({ created_after: new Date("2026-10-01") })) {
  // every page, fetched as you iterate
}

await hf.events.get("evt_...");
await hf.events.deliveries("evt_...");
await hf.events.replay("evt_...", ["ep_..."]); // replay failed/cancelled deliveries of one event

for await (const d of hf.deliveries.listAll({ status: "failed", endpoint_id: "ep_..." })) { /* ... */ }
await hf.deliveries.get("dlv_...");
await hf.deliveries.attempts("dlv_...");
await hf.deliveries.replays("dlv_...");
await hf.deliveries.replay("dlv_...");
```

A `Page` is async-iterable too: `for await (const x of page)` walks that page and every page after it.

### Bulk replay

```js
const preview = await hf.deliveries.bulkReplay({ endpoint_id: "ep_...", statuses: ["failed", "cancelled"], dry_run: true });
console.log(preview.matched, preview.replayed.length, preview.skipped);

let result;
do {
  result = await hf.deliveries.bulkReplay({ endpoint_id: "ep_...", created_after: "2026-10-30T00:00:00Z", limit: 500 });
} while (result.has_more);
```

Fields you leave out take the server defaults: `statuses: ["failed"]`, `limit: 100` (maximum 500) and
`dry_run: false`. Replayed deliveries leave the failed state, so calling again picks up the next batch.

### Endpoints

```js
const ep = await hf.endpoints.create({ url: "https://example.com/hooks", event_types: ["order.created"], max_attempts: 5 });
ep.signing_secret; // whsec_..., store it for verify()

await hf.endpoints.list();  hf.endpoints.listAll();  await hf.endpoints.get("ep_...");
await hf.endpoints.update("ep_...", { enabled: false, description: null }); // only the fields you pass are sent
await hf.endpoints.delete("ep_..."); // archives it
await hf.endpoints.secret("ep_...");
await hf.endpoints.rotateSecret("ep_...", 86400);
```

## Errors

Every API error is thrown as a subclass of `HookFlowError`, with `status`, `code`, `message` and `details` copied
from the API's `{ "error": {...} }` body.

| Status | Error class |
| --- | --- |
| 400 | `BadRequestError` |
| 401 / 403 | `AuthenticationError` / `PermissionDeniedError` (extends `AuthenticationError`) |
| 404 | `NotFoundError` |
| 409 | `ConflictError` (`idempotency_key_reused`, `not_replayable`, `nothing_to_replay`, ...) |
| 413 | `PayloadTooLargeError` |
| 422 | `ValidationError` (`details` lists the field errors) |
| 429 | `RateLimitError` (`retryAfter` in seconds; `code` is `rate_limited` or `quota_exceeded`) |
| 5xx | `InternalServerError` (`retryAfter` when the server sends one) |
| no response | `APIConnectionError`, or `APITimeoutError` for a timeout (`status` is `null`) |

```js
import { HookFlowError, RateLimitError, ValidationError } from "hookflow";

try {
  await hf.events.send("order.created", { order_id: "ORD-101" }, { idempotencyKey: "order-ORD-101-created" });
} catch (err) {
  if (err instanceof RateLimitError) scheduleRetry(err.retryAfter);
  else if (err instanceof ValidationError) console.error("bad event", err.details);
  else if (err instanceof HookFlowError) console.error(err.status, err.code, err.message);
  else throw err;
}
```

## Retries

The client only retries requests that are safe to repeat: `GET`, `DELETE`, and `POST /v1/events` **when you pass an
`idempotencyKey`**. Those are retried up to `maxRetries` times (default 2) after connection errors, timeouts, 429s
and 5xx responses. The client waits for the `Retry-After` time when the server sends one, or backs off exponentially
(0.5s, 1s, ...) when it doesn't. If `Retry-After` is longer than 30 seconds (an exhausted daily quota, for example)
the error is thrown straight away. Every other request is sent once: sending an event without a key, replays, bulk
replays, endpoint create and update. Set `maxRetries: 0` to turn retries off.

## Development

```bash
cd sdks/node
npm install      # dev dependencies only: typescript, @types/node
npm test         # builds dist/ (ESM + CJS + .d.ts), then runs node:test
```
