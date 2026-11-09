# HookFlow vs competitors: research and recommendations

**Date:** 2026-11-06 · Prices and features checked on vendor sites the same day (sources at the end).

## Summary

The webhook-sending market has a clear leader (Svix), a cheaper usage-based challenger (Hookdeck Outpost), and
several open-source or budget options (Convoy, Hook0, Webhook Relay, QStash). All of them already do the basics
HookFlow does: retries, signatures, logs, replay.

HookFlow can't win on basics, and it's behind on two things buyers expect. It can win on being the service that
**proves webhooks arrived and helps customers fix their side**, at a price small teams can afford.

**Recommended order:**

1. **Close two must-have gaps:** sign requests the Standard Webhooks way, and add a customer portal.
2. **Build two differentiators no one offers:** a receiver security check and shareable proof-of-delivery links.
3. **Lean into what's already different:** fast plain-English alerts, a generous free tier, simple self-hosting.
   Add a license so self-hosting is actually allowed.

## The competitors

| | Svix | Hookdeck Outpost | Convoy | Hook0 | Webhook Relay | HookFlow |
|---|---|---|---|---|---|---|
| **Free tier** | 50,000 messages/month, 7-day history | First 50,000 events, 7-day history | Self-host only | 7-day history | 50,000 messages/month | 10,000 events/day (~300,000/month), 30-day history |
| **First paid plan** | $20/mo (30 days); 90 days needs $490/mo | $10 per million events; 30 days needs $499/mo | $999/mo (self-hosted Premium) | €59/mo; Pro €190/mo | $9.99/mo, 35 days | None yet |
| **Customer portal** (end customers manage their own endpoints) | Yes, every plan | Yes | Premium only | Yes | No | **No** |
| **Signatures** | Standard Webhooks | Own format; Standard Webhooks optional | Own format | Own format | Standard Webhooks | **Own format** |
| **Per-endpoint rate limit** | Yes, extra messages are queued | Not listed | Circuit breaking (Premium) | No | No | Limit on parallel requests only |
| **Payload transformations** | Yes | Not listed | Premium | No | No | No |
| **Destinations other than HTTP** | Some | SQS, Pub/Sub, Kafka, S3 and more | HTTP only | HTTP | HTTP | HTTP only |
| **Failure alerts** | Endpoint auto-disabled after ~5 days of failures; email for operational events (since Aug 2025) | "Issues" with email and Slack | Not listed | Not listed | Not listed | **Email after 5 failures in a row, plus a recovery email** |
| **Self-hosting** | MIT | Apache 2.0, same features as managed | Elastic 2.0 | SSPL | No | Docker, **but no license file** |
| **Compliance** | SOC 2 (Professional+), HIPAA BAA (Enterprise) | SOC 2; HIPAA on Growth | Enterprise | GDPR, EU hosting | SOC 2 | None |

What this shows:

- **Long history is expensive everywhere.** Svix and Hookdeck charge about $500/month for 30–90 days of history.
  HookFlow keeps 30 days on the free tier. That's a real, easy-to-explain advantage.
- **The customer portal is standard.** Svix's main selling point is a page you embed so *your* customers add
  their own endpoints and see their own logs. HookFlow only lets the account owner add endpoints, so it can't yet
  replace Svix for a SaaS company sending webhooks to its customers.
- **Standard Webhooks is becoming the norm.** Svix, Webhook Relay, Resend, Clerk and Supabase use it. Receivers
  can verify those requests with one shared library, which they can't do with HookFlow's own headers.
- **Failure alerts are slow or need setup elsewhere.** Svix disables an endpoint only after about five days of
  failures. Hookdeck's alerts go through its Issues feed or integrations. HookFlow's email after 5 failures in a
  row, with a "back to normal" email and replay link, is already faster and simpler.
- **Nobody checks the customer's side.** I found no provider that tests whether a customer's endpoint really
  verifies signatures, or offers shareable proof of delivery for support teams. Stripe and Fintoc only
  *document* how to test this by hand.

## Where HookFlow stands

**Ahead**
- 30-day history on the free tier, where others charge ~$500/month.
- A higher free volume: about 300,000 events a month versus 50,000.
- Failure alerts within minutes, with a recovery email that links to replay.
- Plain-English delivery explanations ("Gave up after 3 of 3 attempts, your server returned 503").
- A live demo visitors can try before signing up, and one-container self-hosting.

**On par**
- Retries with backoff and custom schedules.
- HMAC signatures with secret rotation.
- Replay and bulk replay.
- Teams and roles, scoped API keys, an audit log.

**Behind**
- No customer portal.
- Own signature format instead of Standard Webhooks.
- No per-endpoint rate limit (only a cap on parallel requests).
- No transformations and no non-HTTP destinations.
- No paid plan, uptime promise or compliance reports.
- No license, so legally nobody may self-host or reuse the code yet.

## Recommendations

### A. Close the must-have gaps

**A1. Standard Webhooks signatures.** *Effort: about a day.*

- Also send `webhook-id`, `webhook-timestamp` and `webhook-signature` (with `whsec_` secrets), keeping the
  current `HookFlow-*` headers so nothing breaks.
- Receivers can then use the official Standard Webhooks libraries.
- It also makes switching from Svix easy, because receivers' verification code keeps working.

**A2. Customer portal.** *Effort: about a week.* **Done (2026-11-07).**

- A HookFlow customer creates a "consumer" (one of their own customers) and gets a signed, expiring link to a
  small page.
- On that page, their customer adds endpoints, picks event types, sees delivery logs and replays, limited to
  their own data.
- This is the feature that lets a SaaS company use HookFlow for customer-facing webhooks. Without it, HookFlow
  only suits internal use.

**A3. Per-endpoint rate limit.** *Effort: 1–2 days.*

- Let an endpoint say "at most N requests per second". Extra deliveries wait in the queue instead of failing.
- The existing parallel-request limit is part of this already.

### B. Differentiators no one offers

**B1. Receiver security check.** *Effort: about a day.* **Done (2026-11-06).**

- A button on the endpoint page: "Check my endpoint".
- HookFlow sends signed test requests: a valid one, then one with a wrong signature, an old timestamp and a
  missing signature header.
- It reports, for example: "Your endpoint accepts requests with a wrong signature, so anyone can send it fake
  events. Here's how to verify signatures in Node, Python and Go."
- Show a "Signature verified ✓" badge on endpoints that pass.
- Easy to demo, valuable to security-minded buyers, and nobody does it.

**B2. Proof-of-delivery links.** *Effort: about a day.*

- From any delivery, create a read-only link (expiring after 7–30 days, can be revoked).
- The link shows the event, the exact request sent, each attempt, and the customer server's response and timing.
- Support teams paste it when a customer says "we never got it". Silent failures and "debugging without logs" are
  the most common webhook complaints. This turns HookFlow's logs into a support tool and shows the HookFlow brand
  to the customer's customers too.

**B3. Endpoint doctor.** *Effort: 1–2 days.*

- When an endpoint fails, diagnose the cause instead of only showing a status code. Examples:
  - expired or invalid security certificate (TLS);
  - the address doesn't exist any more (DNS);
  - connection refused;
  - a timeout, showing how long it took;
  - a 401 or 403, which usually means the signing secret is wrong;
  - a 413, meaning the payload is too large;
  - a redirect, which HookFlow doesn't follow.
- Give each one a one-line fix, and include the diagnosis in the failure alert email.
- This builds on HookFlow's plain-English explanations, which competitors don't stress.

**B4. Gentle catch-up after an outage.** *Effort: 2–3 days.*

- When an endpoint recovers, deliver the backlog at a rising rate (for example 1, 2, 5, 10 per second) instead of
  all at once, which can knock a just-recovered server over again.
- Show "Catching up: 340 left" on the endpoint page.
- Svix queues extra messages but doesn't ramp up after outages.

**B5. Payload change warnings.** *Effort: 2–3 days.*

- Learn the shape of each event type from recent events.
- Warn in the dashboard (and optionally block) when an event arrives with a field removed or its type changed:
  "order.paid: `total` is missing; 214 past events had it".
- Svix stores schemas but doesn't check messages against them; breaking-change detection exists only in separate
  tools.

### C. Positioning and pricing

- **Tagline idea:** "Webhooks that arrive, and proof that they did." It sums up retries, alerts, the security
  check and proof links.
- **Target buyer:** small and mid-size SaaS teams that find Svix's $490/month too much but need real history and
  alerts. Hook0, Webhook Relay and Svix's $20 plan all keep a week or less, or have no portal.
- **Pricing to consider when adding paid plans:**
  - keep the free tier (10,000 events/day, 30-day history);
  - a ~$19–29/month plan with the customer portal, 90-day history and higher limits;
  - pay-as-you-go above that (Hookdeck charges $10 per million events, so stay at or below it).
- **Add a license.** MIT or Apache 2.0 makes "self-host for free" a real selling point, like Svix and Hookdeck.
  Without one, nobody may legally run the code.
- **Say what's different on the home page:**
  - a comparison table like the one above, kept factual and dated;
  - "30-day history free";
  - "Alerts in minutes, not days";
  - once built, "We check your customers' endpoints are secure".

## Suggested roadmap

| Order | Item | Effort | Why now |
|---|---|---|---|
| 1 | Add a license (A, C) | Minutes | Needed for self-hosting claims |
| 2 | Standard Webhooks signatures (A1) | ~1 day | Industry norm; easy switch from Svix |
| 3 | Receiver security check (B1) | ~1 day | Unique, easy to demo |
| 4 | Proof-of-delivery links (B2) | ~1 day | Unique; addresses the top complaint |
| 5 | Customer portal (A2) | ~1 week | Needed for SaaS customer-facing use |
| 6 | Endpoint doctor (B3) | 1–2 days | Builds on existing explanations |
| 7 | Per-endpoint rate limit (A3) and gentle catch-up (B4) | 3–5 days | Reliability story |
| 8 | Payload change warnings (B5) | 2–3 days | Nice extra |
| 9 | Paid plan, uptime promise, compliance work | Ongoing | When there are paying users |

## Caveats

- Many comparison pages are written by the vendors themselves, and each ranks itself first. I used vendor pricing
  pages for numbers where I could. Where a number comes from a third-party comparison (mainly Hook0 and Webhook
  Relay), it's labelled as such in the sources.
- Prices and features change often. Re-check before publishing a comparison on the website.
- "No one offers this" means I found no evidence of it in public docs on 2026-11-06, not that it's impossible
  someone has it.

## Sources

- Svix pricing (official): https://svix.com/pricing
- Svix retries and endpoint disabling: https://docs.svix.com/retries
- Svix throttling: https://docs.svix.com/throttling
- Svix event types and schemas: https://docs.svix.com/event-types
- Hookdeck Outpost pricing (official): https://hookdeck.com/outpost/pricing.md
- Hookdeck Outpost vs Svix (vendor-written): https://hookdeck.com/webhooks/platforms/hookdeck-outpost-vs-svix-dispatch-webhook-sending-comparison
- Hookdeck Issues and Sentry integration: https://hookdeck.com/docs/guides/sentry-integration
- Convoy pricing (official): https://www.getconvoy.io/pricing
- Comparison of Svix, Outpost, Convoy, Hook0, QStash and Webhook Relay, 2026-10-11 (written by Webhook Relay):
  https://webhookrelay.com/blog/webhooks-as-a-service-comparison/
- Svix's own comparison pages (vendor-written): https://svix.com/alternatives/hookdeck-outpost/,
  https://svix.com/alternatives/convoy/
- Standard Webhooks overview: https://webhookrelay.com/glossary/standard-webhooks/
- Testing signature verification by hand (Stripe, Fintoc): https://docs.stripe.com/automated-testing/webhooks,
  https://docs.fintoc.com/docs/resources/webhooks-walkthrough/webhooks-validating.md
- Common webhook complaints (vendor blog, anecdotal): https://dev.to/serwetarslan/your-webhooks-are-failing-silently-heres-how-we-fixed-itpublished-false-2ajd
- Svix pricing concerns (review site): https://us.fitgap.com//products/015651/svix
