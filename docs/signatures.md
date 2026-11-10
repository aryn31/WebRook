# Webhook signatures and the security check

How HookFlow signs every request, how a receiver checks it, and how the **signature check** on each endpoint
page tests that a receiver does this correctly.

## 1. Why sign requests

A webhook endpoint is a public URL. Anyone who finds it can send it a request, for example a fake
`order.paid` event. A signature lets the receiver prove two things before trusting a request:

- it came from HookFlow, because only HookFlow and the endpoint's owner know the secret;
- nobody changed it on the way, because any edit breaks the signature.

## 2. How HookFlow signs a request

Each endpoint has its own **signing secret** (`whsec_…`), shown on the endpoint page under "Signing secret".

For every request, HookFlow:

1. Builds the text to sign: the Unix timestamp, a dot, and the exact request body.
   ```
   1793612400.{"type":"order.paid","data":{"total":4999}}
   ```
2. Computes HMAC-SHA256 of that text with the endpoint's secret, and writes it as `v1=<hex>`.
3. Sends both in headers. The secret itself is never sent.
   ```
   HookFlow-Timestamp: 1793612400
   HookFlow-Signature: v1=8409e83bba7930c246daa2c2ffdd88edd590e667ce9d961964e2531b890e02d1
   ```

HMAC is one-way: you can't work out the secret from a signature. A one-character change to the body, or a guessed
secret, gives a completely different result. With secret `whsec_demo123`:

| Request | Signature |
|---|---|
| The real request | `v1=8409e83b…02d1` |
| `total` changed from 4999 to 1 | `v1=0a69370c…b467` |
| Signed with a guessed secret | `v1=d86bcc5c…d7cd` |

**Standard Webhooks headers.** Every request is also signed the
[Standard Webhooks](https://www.standardwebhooks.com) way, with the same secret and timestamp:

```
webhook-id: evt_01JD8…            (the event ID, the same on every retry)
webhook-timestamp: 1793612400
webhook-signature: v1,K5oZfzN95Z9UVu1EsfQmfVNQhnkZ2pj9o9NDN/H/pI4=
```

The signed text is `{webhook-id}.{webhook-timestamp}.{body}`, base64-encoded. The HMAC key is the base64-decoded
part of the secret after `whsec_`. The official Standard Webhooks libraries verify this in one call.

Secrets are `whsec_` plus standard base64 of 24 random bytes. Secrets made before 2026-11-10 used base64url, which
strict libraries reject. The dashboard flags them as legacy, and rotating fixes it. HookFlow's own header works with
either kind.

**Secret rotation.** After "Rotate" on an endpoint, requests carry two signatures for the grace period:
`v1=<new>,v1=<old>`. Receivers keep working until they switch to the new secret.

Code: [backend/app/signing.py](../backend/app/signing.py) (signing) and
[backend/app/worker/engine.py](../backend/app/worker/engine.py) (headers on each delivery).

## 3. How a receiver checks a request

The receiver needs the endpoint's signing secret, stored as an environment variable. For every request:

1. **Read the raw body**, exactly as received, before any JSON parsing. Re-encoding JSON can change spacing or
   key order, and then the signature won't match.
2. **Read `HookFlow-Timestamp` and `HookFlow-Signature`.** If either is missing, reject.
3. **Check the timestamp is within 5 minutes of now.** This stops an attacker who captured a real request from
   sending it again later. The timestamp is part of the signed text, so it can't be changed without breaking the
   signature.
4. **Compute** `"v1=" + HMAC-SHA256(secret, timestamp + "." + raw body)`.
5. **Compare** with each comma-separated value in the header, using a constant-time comparison
   (`crypto.timingSafeEqual`, `hmac.compare_digest`). Accept if any one matches.
6. **Reply.** If the request is genuine, process it and return 2xx. If any check fails, return **400 or 401** and
   do nothing. Avoid 5xx: senders treat it as "try again later".

Also skip duplicates. Delivery is at-least-once, so store each `HookFlow-Event-Id` you've handled and ignore
repeats.

The easiest way is a [Standard Webhooks](https://www.standardwebhooks.com) library, which checks the
`webhook-*` headers, including the timestamp:

```js
import { Webhook } from "standardwebhooks";
const event = new Webhook(process.env.HOOKFLOW_WEBHOOK_SECRET).verify(rawBody, req.headers);
```

The HookFlow SDKs check the `HookFlow-*` headers instead, also in one call:

```js
import { verify } from "hookflow";
const event = verify(rawBody, req.headers, process.env.HOOKFLOW_WEBHOOK_SECRET); // throws if not genuine
```
```python
from hookflow.webhooks import verify
event = verify(request.get_data(), request.headers, os.environ["HOOKFLOW_WEBHOOK_SECRET"])
```

Full examples: [docs/api.md](api.md#verifying-the-signature), [sdks/node](../sdks/node/README.md),
[sdks/python](../sdks/python/README.md), and the local test receiver [receiver/receiver.py](../receiver/receiver.py).

## 4. The signature check

Many receivers skip some or all of section 3, and nothing breaks until someone sends them a fake event. The
signature check finds this out.

### What the user sees

On an endpoint's page, the **Signature check** card has a **Check my endpoint** button. A few seconds later it
shows a verdict, each test with what should have happened and what did, and fix code when needed. The verdict
also appears as a badge next to the endpoint's name and on the Endpoints list.

### The five test requests

HookFlow sends these at the same time. Each one has event type `hookflow.security_check` and a
`HookFlow-Security-Check: <name>` header, so the receiver can recognise and ignore them. Each request carries both
signature styles (HookFlow and Standard Webhooks), forged the same way, so the check works whichever one the
receiver verifies.

| Name | What's sent | A safe endpoint should |
|---|---|---|
| `valid` | Correctly signed, current timestamp | **Accept** (2xx) |
| `wrong_signature` | Signed with a random secret | Reject |
| `tampered_body` | Signed, then a field added to the body | Reject |
| `old_timestamp` | Correctly signed, but the timestamp is an hour old | Reject |
| `missing_signature` | No `HookFlow-Signature` header | Reject |

Any answer that isn't 2xx counts as "rejected". A 5xx rejection still counts, but the card suggests 400 or 401
instead.

### Verdicts

They're decided in this order:

1. **Inconclusive.** Either the genuine request wasn't accepted (endpoint down, or rejects unknown event types),
   or some test got no answer at all (timeout, connection error). We can't judge, so the card asks to fix that and
   run it again.
2. **Not verifying (`fail`).** It accepted a wrong signature, an edited body or a missing signature. Anyone can
   send it fake events.
3. **Partly verified (`partial`).** Signatures are checked, but the hour-old request was accepted, so captured
   requests can be replayed.
4. **Verified (`pass`).** It accepted the genuine request and rejected all four forged ones.

### How it's built

- **Route:** `POST /v1/endpoints/{id}/security-check`, in
  [backend/app/routers/endpoints.py](../backend/app/routers/endpoints.py).
  - It needs the `endpoints:write` permission and only works on endpoints in your account.
  - Each endpoint can be checked 6 times a minute.
  - It returns the endpoint with its new `security_check` result.
- **Test requests:** [backend/app/security_check.py](../backend/app/security_check.py).
  - It builds the five requests and sends them in parallel threads.
  - It uses the same `send()` as real deliveries, so it gets the same timeouts, the same 4 KiB cap on stored responses, no
    redirects, and the same block on private and internal addresses.
  - During a secret rotation, the genuine request is signed with both secrets, like a real delivery.
- **Storage:** the result (verdict, summary, time and each test's outcome) is saved in
  `endpoints.security_check`, a JSONB column added by migration `0008`.
  - Changing the endpoint's URL clears it, since the old result was for the old URL.
  - Each run is recorded in the audit log as `endpoint.security_checked`, with the verdict.
- **Dashboard:** [frontend/components/SecurityCheck.tsx](../frontend/components/SecurityCheck.tsx) contains:
  - `SecurityCheckCard`: the card on the endpoint page;
  - `SecurityBadge`: the badge used on the endpoint page and the Endpoints list.
- **Tests:** [backend/tests/test_security_check.py](../backend/tests/test_security_check.py) uses fake receivers
  for each kind of result: passing, failing, partial, inconclusive, 5xx rejections, a URL change, secret rotation,
  permissions and the rate limit.

### Trying it locally

The test receiver in `docker-compose.yml` has a strict path, `/secure`. It answers 401 unless the signature is
valid and recent.

1. Add an endpoint with URL `http://receiver:9000/secure` and copy its signing secret.
2. Restart the receiver with that secret:
   `RECEIVER_SECRET=whsec_… docker compose up -d receiver`
3. Click **Check my endpoint**. It should say **Verified**.
4. Do the same with an endpoint on `http://receiver:9000/hooks`, which accepts everything. It should say
   **Not verifying**.

### What it doesn't catch

- **Only five cases are tested.** A receiver could still have other bugs, for example verifying against the
  parsed JSON instead of the raw body. That one usually shows up as failed genuine requests, which makes the check
  inconclusive.
- **It's a snapshot.** If the receiver's code changes later, run the check again.
- **"Accepted" only means a 2xx answer.** A receiver that answers 200 but quietly ignores forged requests will
  look like it accepted them. Answering 400 or 401 gives an honest result.
