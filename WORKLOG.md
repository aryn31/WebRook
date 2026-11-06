# HookFlow Work Log

A record of what was done in each work session, newest first. Add an entry at the end of every session.

Each entry covers: what was built or changed, decisions made, how it was checked, and what's left.

---

## 2026-11-06 — Public pages and unverified sign-ups

### Done
- **Email alerts when an endpoint keeps failing** (the last Milestone 4 item):
  - Each endpoint counts failed attempts in a row (migration `0007`: `consecutive_failures`, `failing_since`,
    `alert_sent_at` on endpoints; `failure_alerts` on users). At 5 (`ALERT_AFTER_FAILURES`, 0 = off) the
    account owner and admins get "Alert: <endpoint> is failing" with the URL, count, start time and last error.
    Nothing more while it stays down. The next success sends "Resolved: <endpoint> is working again" with how long
    it was down and how many deliveries failed, linking to the endpoint page to replay them.
  - `app/alerts.py`: decided inside the transaction that records the attempt (row-level update, so one alert
    even with many workers); sent after commit and never breaks delivery. If no email could be sent, the alert
    isn't marked sent, so the next failure tries again.
  - `PATCH /v1/auth/preferences` with a switch on the Security page ("Email alerts"); audit action
    `auth.preferences_changed`. Endpoint page notes when owners and admins were emailed.
  - Checked: 8 new tests in `tests/test_alerts.py`; all 205 backend tests pass; migration down and up; live run
    on the local stack (5th failure sent the alert, fixing the URL sent the recovery email, console mail mode,
    then back to Gmail); email previews; screenshots. Alerts turned off for the local test account so it never
    emails its fake address.
  - Docs: `docs/api.md`, `docs/operations.md` (`ALERT_AFTER_FAILURES`), PRD Milestone 4 marked complete.
  - Deploying: just commit and push. Render runs migration `0007` on start; Gmail sending is already set up.
- **Contact page** (`/contact`, linked in the site header and footer): a form (name, email, topic chips, message)
  and a Support panel with wendfolk02@gmail.com (open email / copy). Logged-in visitors get their email filled in.
  `POST /v1/contact` emails the message to `SUPPORT_EMAIL` (default wendfolk02@gmail.com) with Reply-To set to
  the sender, so replying answers them. Spam: hidden honeypot field, 5 per hour per IP and per email; HTML is
  escaped. The mailer gained a `reply_to` option. The Privacy and Terms pages show the address too (was GitHub
  issues). Checked: 6 new tests (211 pass); a real send through the local stack (console mail mode, then back
  to Gmail); screenshots in dark, light and the sent state.
- **Fixed contact-page shortcuts:** "Reset your password" sent logged-in visitors to the dashboard (the reset page
  is for logged-out people). Logged-in visitors now see "Change your password" (→ Security). Internal links switch
  pages instantly instead of reloading. Clicked through all four, logged in and out.
- **Competitor research:** `docs/competitive-analysis.md` compares Svix, Hookdeck Outpost, Convoy, Hook0 and
  Webhook Relay (prices checked today) with HookFlow, and recommends: Standard Webhooks signatures, a customer
  portal, a receiver security check, proof-of-delivery links, an endpoint doctor, gentle catch-up after outages,
  payload change warnings, and adding a license (the repo has none).
- **Fixed:** someone who signed up but hadn't entered their email code saw "Dashboard" on the home page (the
  session exists, so `/v1/auth/me` answers). `AuthCta` now checks `email_verified`: unverified visitors see
  "Verify email" in the top bar and "Finish signing up" in the hero, both going to `/verify-email`. Verified users
  still see "Dashboard"; logged-out visitors still see Log in / Sign up. Checked with screenshots of both cases.

## 2026-11-05 — Forgot password and show/hide password

### Done
- **Forgot password:** "Forgot password?" on the log-in page opens `/forgot-password`. Enter your email, get a
  6-digit code (same rules as verification codes), then enter it with a new password. Every session is signed
  out and this browser is logged in. New routes `POST /v1/auth/forgot-password` and
  `POST /v1/auth/reset-password`; audit action `auth.password_reset`. The first route answers the same whether or
  not the account exists, sends the email after responding, and skips too-frequent requests quietly, so it can't
  be used to find accounts. A reset also marks the email verified, since the code proves ownership.
- **Reset email:** "Reset your HookFlow password", same dark design as the verification email (the two now share
  one template), code kept out of the subject.
- **Show/hide password:** an eye button on every password field (log in, sign up, Security page, reset page),
  in a new `PasswordInput` component.
- Checked: 9 new tests in `tests/test_password_reset.py`; all 197 backend tests pass; frontend typecheck; end to
  end through the local dashboard proxy (with `MAIL_BACKEND=console` for the test, then put back to `gmail`);
  screenshots of the log-in and reset pages.
- **Back button fixed:** after logging in, Back went to the log-in page. Now:
  - logging in or out, signing up, verifying and resetting replace the page in history (`lib/navigation.ts`), so
    Back skips them;
  - the log-in, sign-up and reset pages send an already logged-in browser to the dashboard (the page passes
    whether the session cookie exists, and the API confirms it);
  - `FreshOnBack` reloads auth and dashboard pages that the browser restores from memory on Back, so a
    logged-out dashboard is never shown.
  Checked in headless Chrome: landing → log in → Back lands on the landing page; opening `/login` or `/register`
  while logged in goes to Overview; Back after logging out stays on the log-in page.
- **Home page redesign** (to make visitors want to try it):
  - **Live demo** (`components/landing/Playground.tsx`): a pretend HookFlow in the browser, sped up. Send
    events, click an endpoint to take it down, watch 503s retry with countdowns, fail after 4 attempts, then
    replay. Autoplays a short story (billing goes down and recovers) until the visitor clicks anything; only runs
    while on screen. Nothing talks to the API.
  - New sections: a facts strip, a feature grid with small visuals (retries, signatures, replay, endpoint health,
    teams), "Live in three steps", and an FAQ. Hero gets a "Free to start · No card · No SDK" line and a link to
    the demo; the top bar gets "Live demo". All claims match current features and default limits.
  - Sections fade in on scroll (`components/landing/Reveal.tsx`; off with reduced motion, visible without JS).
  - Checked: desktop, phone and light mode screenshots; drove the demo in headless Chrome (down → retries →
    failed → back up → replay → delivered).
- **Dashboard redesign** (the logged-in pages):
  - Overview: greeting with the person's name; a summary card with a success-rate ring, a plain-English verdict
    ("Everything's arriving" / "Most deliveries are failing" / "Quiet so far"), a bar showing the delivery mix and
    linked counts; an "Endpoint health" list (worst first) next to Usage.
  - Endpoints page: cards instead of a table, each with a coloured edge, health bar, last error and event types.
  - Events page: event type first with the ID underneath and a small coloured badge; failures marked by a red
    edge instead of tinting whole rows.
  - Everywhere: sidebar grouped into Monitor / Configure / Account, user chip with initials and role; shimmer
    placeholders instead of "Loading…"; empty states with an icon (green tick when empty is good); soft lime
    glow at the top of each page; row hover in tables.
  - Checked: screenshots of a busy account and a brand-new one, light and dark mode, phone width.
- **Theme switch (Light / Dark / System):** in the sidebar, the site header and footer, and the corner of the
  log-in pages (`components/ThemeToggle.tsx`). Saved in the browser (`hf-theme`); a tiny script in `<head>`
  applies it before the page draws, so there's no flash. Dark styles in `globals.css` now apply when the system
  is dark and Light wasn't picked, or when Dark was picked. The live demo and photo panels stay dark on purpose.
  Checked in headless Chrome: picking Light on a dark system, the choice carrying to other pages, Dark on a light
  system, and back to System.
- **Remaining dashboard pages redesigned:**
  - Single event: big title with a coloured badge; a route diagram (`components/FanOut.tsx`) from the event to
    each endpoint, lines coloured by result with status code and attempts; colour-coded JSON payload
    (`components/JsonView.tsx`).
  - Single endpoint: titled by its description; a health card (success ring, verdict, last error, attempts /
    succeeded / failed / last attempt); "Settings" list; signing secret and test event side by side.
  - API keys: key icon, prefix chip, colour-coded access (full / send only / read only / custom).
  - Team: avatars with a stable colour per person (`components/Avatar.tsx`; the sidebar uses the same initials).
  - Security: device icons (laptop / phone / terminal) for sessions; tips for a strong password beside the form.
  - Audit log: coloured icon per kind of action (`components/AuditIcon.tsx`); "auth.email_verified" now reads
    "Email verified".
  - The success ring is now shared (`components/Ring.tsx`). Checked in dark, light and phone width.
- No new settings, so deploying is just commit and push.

## 2026-11-04 — Milestone 4 deployed

### Done
- Ran the full stack locally with Docker Compose. Migration 0004 applied to the local database, and `/health/ready`
  reported the database, Redis and worker all OK.
- The user committed Milestone 4 (`90eef35`) and deployed it to Render and Vercel. Nothing needs to run locally
  for production.
- Added `.github/workflows/keep-awake.yml`: pings `/health/live` every 5 minutes so Render's free plan doesn't
  sleep. It does nothing until the repository variable `HOOKFLOW_API_URL` is set in GitHub.
- The user set `HOOKFLOW_API_URL`, `TRUSTED_PROXY_COUNT=2` and `METRICS_TOKEN`.
- PRD updated to v1.3 (`docs/PRD.md`): a "What changed in v1.3" section, Milestone 4 marked complete except email
  alerts, and the custom-schedule, pattern and launch decisions recorded. `docs/HookFlow-PRD-v1.3.pdf` (33 pages)
  replaces the v1.2 PDF, built from the Markdown with headless Chrome as before.

- **Security page** (dashboard → Security): change your password, see where you're logged in (device, IP, last
  active), sign out one session or all others. Changing the password signs out every other session and gives this
  browser a new token. New routes: `POST /v1/auth/password`, `GET /v1/auth/sessions`,
  `DELETE /v1/auth/sessions/{id}`, `POST /v1/auth/sessions/sign-out-others`. Migration `0005` adds `ip_address`,
  `user_agent` and `last_seen_at` to sessions (`last_seen_at` is written at most every 5 minutes). Security events
  go in the person's own audit log, even while working in a team.
- Checked: 11 new tests in `tests/test_account_security.py`; all 174 backend tests pass; migration up and down;
  frontend typecheck; end to end through the dashboard proxy with two browsers (the other one was signed out after
  the password change); screenshot of the page.
- **Render deploy crash fixed:** the Security page deploy built fine but the worker crashed on start
  (`No module named 'packaging'`). `kombu` wasn't pinned, so Render's fresh build got a newer version that needs
  `packaging` without installing it; the local image still had older cached versions. Pinned `kombu==5.6.2` and
  `packaging==26.3` in `backend/requirements.txt`, and checked with a `--no-cache` build.
- **Email verification:** new sign-ups get a 6-digit code by email and can only verify, resend or log out until
  they enter it (`403 email_unverified` everywhere else). Existing accounts were marked verified (migration
  `0006`, which also adds the `email_codes` table). Codes are stored as an HMAC keyed with
  `SECRET_ENCRYPTION_KEY`, last 15 minutes, allow 5 wrong guesses, and can be resent after 60 seconds (5 per hour).
  Signing up with an email whose account was never verified replaces that account, so nobody can squat an
  address. New routes: `POST /v1/auth/verify-email`, `POST /v1/auth/resend-verification`. Dashboard: a
  `/verify-email` page (auto-submits at 6 digits, resend countdown, "use a different email"); login, sign-up and
  any `email_unverified` answer send people there.
- **Sending email** (`app/mailer.py`): `MAIL_BACKEND` = `console` (default; logs the code), `gmail`, `smtp` or
  `brevo`. Recommended: `gmail`, the Gmail API over HTTPS from the user's own account (Render's free plan blocks
  SMTP ports). `backend/scripts/gmail_token.py` (stdlib only, run locally) does the OAuth sign-in with PKCE and
  prints the refresh token; the backend caches access tokens and retries once on a 401. Setup is in
  `docs/operations.md#email`. The Google app must be published ("In production"), or tokens expire after 7 days.
- Checked: 14 new tests in `tests/test_email_verification.py`; all 188 backend tests pass; migration up and down;
  frontend typecheck; end to end locally (blocked before the code, wrong code counted, right code unlocks);
  screenshot of the page.
- **Verification email design** (`app/email_templates.py`): HTML in the website's dark theme (near-black, cream
  text, lime code and italic serif accent; Instrument Serif and Geist where the mail app loads web fonts), built
  with tables and inline styles so Gmail, Outlook and Apple Mail show it the same, plus a plain-text version. Large code, expiry note, "Enter code in
  HookFlow" button, and a "didn't sign up?" note. Links use the new `APP_URL` setting (set it on Render to
  `https://web-rook.vercel.app`). Checked at desktop and phone widths.
- **Code kept out of the subject:** the subject is now "Confirm your email for HookFlow" and the preview line only
  says when the code expires, so the code doesn't show in notifications, on a lock screen or in the inbox list.
  The test checks the code isn't in the subject.
- **Privacy policy and terms** at `/privacy` and `/terms` (public, linked in the site footer), for Google's
  sign-in screen and the public site. They describe what is actually stored and for how long. The contact is the
  GitHub issues page unless `NEXT_PUBLIC_CONTACT_EMAIL` is set on Vercel.
- **Before deploying:** set the `MAIL_BACKEND=gmail` settings on Render, or new users can't finish signing up.
- Offered but not chosen yet: two-factor login, blocking leaked passwords, longer lockouts after repeated failures.

### Left to do
- Check the free Postgres expiry date on Render, and that the audit log shows real IPs.
- Email alerts when an endpoint keeps failing (the last Milestone 4 item).
- Optional: publish the SDKs to PyPI and npm and update the resume text with the Milestone 4
  features.

## 2026-11-02 — Milestone 4 (Product Improvements)

**Outcome:** Everything in Milestone 4 except email alerts: team accounts, scoped API keys, pattern subscriptions,
custom retry schedules, bulk replay, and Python and Node SDKs. Endpoint health was already done.

### Built
- **Team accounts** (`app/routers/team.py`, `app/permissions.py`, `app/deps.py`):
  - An account is still identified by its owner's user ID, so no data moved. `Principal.user` is the account and
    `Principal.actor` is the person acting.
  - Roles: owner (implicit), admin, developer, viewer. Every route needs one permission (see the table in
    `docs/api.md#permissions`).
  - Invites are one-time links (`/invite/<token>`, hash stored, 7 days). No email is sent. The invitee must be
    logged in with the invited email. A new invite to the same email replaces the old link.
  - Sessions have an `account_id`. `POST /v1/auth/switch-account` changes it; removed members fall back to their
    own account. `GET /v1/auth/me` returns the account, role, permissions and every account the user can switch to.
  - Only the owner can manage admins. The owner can't be removed or changed.
  - Audit entries record the acting user (`actor_user_id`); the API returns their email.
- **Scoped API keys:** seven scopes (`events:write`, `events:read`, `deliveries:read`, `deliveries:replay`,
  `endpoints:read`, `endpoints:write`, `audit:read`). A key can't have more than its creator's role. Keys made before
  this have NULL scopes and keep full access. `GET /v1/api-keys/scopes`.
- **Pattern subscriptions:** `order.*` matches every type starting with `order.`. Ingest turns the event type into
  every matching pattern and uses the same indexed `IN` query.
- **Custom retry schedules:** `endpoints.retry_schedule`, 1–9 waits of 1s–24h; the last repeats. ±10% jitter, and
  a longer `Retry-After` still wins. Read at retry time, so a change affects deliveries already retrying.
- **Bulk replay:** `POST /v1/deliveries/replay` with endpoint, event type, status and time filters, up to 500 per
  request, `dry_run`, and its own rate limit (`BULK_REPLAY_RATE_LIMIT_PER_MINUTE`, 10/min). Only enabled endpoints.
- **Migration `0004`:** `account_members`, `account_invites`, `sessions.account_id`, `api_keys.scopes` and
  `created_by_user_id`, `endpoints.retry_schedule`, `audit_logs.actor_user_id`. Backfills the creator and actor
  columns with the account owner.
- **SDKs** (`sdks/python`, `sdks/node`, built by a helper agent): webhook verification, a client for events,
  deliveries (including bulk replay) and endpoints, auto-pagination, typed errors. No runtime dependencies.
  Retries only safe requests (and `POST /v1/events` with an idempotency key).
- **Dashboard:**
  - API keys: access presets (full, send only, read only, custom) and an Access column.
  - Endpoints: patterns in the event-types input; retry timing (default or custom) on create, edit and details.
  - Bulk replay: on an endpoint's page and on the Failed tab of Deliveries, with a check before replaying.
  - Buttons the role can't use are hidden (`components/MeContext.tsx` provides `useMe().can(...)`).
  - Audit log: names the person, and labels for the new actions.
  - Team page, invite page and account switcher (built by a helper agent): `/team` (members, roles, invite
    links, open invites, a roles table), `/invite/<token>` (accept, wrong-email and expired states), and an account
    picker in the sidebar. Log in / Sign up links now keep `?next=` so a new invitee comes back to the invite.
- **Docs:** `docs/api.md` (permissions, team, scopes, patterns, retry schedule, bulk replay; fixed the signature
  snippets), README, PRD status, `docs/operations.md`.

### Decisions
- **Tenancy stays on the owner's user ID** rather than a new `accounts` table. Every existing query and index keeps
  working; a team is "the owner's account plus members".
- **Keys belong to the account**, not the person, so they keep working when the creator leaves. Their scopes are
  capped at creation time.
- **Invites by link, not email**, because email isn't set up yet (it's the remaining Milestone 4 item).

### Bugs found and fixed
- Admins could revoke an owner's admin invite though they can't create one. Now only the owner can.
- The doc's Node verification snippet threw on a non-ASCII signature (it compared string length, not byte length)
  and skipped the timestamp check for a non-numeric timestamp. The Python one raised on a bad timestamp. Both fixed.
- The webhook example body showed `created_at` without microseconds; the real body has them.

### Checked
- `pytest`: 163 passed (39 new in `tests/test_milestone4.py`).
- Migration `0004` upgrades and downgrades cleanly; `alembic check` finds no difference from the models.
- SDKs: Python 69 passed, Node 47 passed, offline. They cross-check signatures against `backend/app/signing.py` and
  the doc snippets.
- Frontend typecheck and `next build` pass.
- End to end in a throwaway Docker stack: a send-only key could send but got 403 reading; an `order.*` endpoint got
  `order.item.added`; with `retry_schedule: [3]` the second attempt came 3.3s after the first; after fixing the URL,
  bulk replay (dry run, then real) delivered it. Dashboard pages all return 200.
- The helper agent checked the team flow in headless Chrome: invite, wrong-email rejection, role change, switching
  accounts, leaving, in light, dark and phone widths.

### Left
- Email alerts.
- The PRD PDF (`docs/HookFlow-PRD-v1.2.pdf`) predates the Milestone 4 status notes in `docs/PRD.md`.
- SDKs are tested on Python 3.12 and Node 26 only; the declared minimums (3.10, 18) weren't available.
- SDKs aren't published to PyPI or npm.
- Ideas from building the UI: a public invite preview so the sign-up page can say who invited you; show who sent
  each invite.

---

## 2026-11-02 — Attempt counts after replays

**Outcome:** Every delivery message now counts attempts from the last replay, so a delivery replayed many times no
longer shows numbers like "Attempt 63 failed".

### Found
- The table and the "failed" / "processing" messages already used the per-run count (added in Milestone 3). Three
  messages on the delivery detail still used the running total.

### Changed
- `frontend/lib/format.ts` (`explainDelivery`):
  - Delivered: "on attempt N" counts from the last replay.
  - Retrying: "Attempt 2 of 5 failed…" instead of "Attempt 62 failed…".
  - Pending after a replay: "Replay queued — attempt 1 of 5…" instead of "attempt 63".
- The full running total is still shown in the table's tooltip and in the attempt history.

### Checked
- `tsc --noEmit` passes.

---

## 2026-11-02 — Log in / Sign up on the public pages

**Outcome:** Logged-out visitors always see Log in and Sign up on the home and Platform pages, and those buttons open
`/login` and `/register`. A confirmed session swaps them for Dashboard.

### Found
- On the live site, logged-out visitors are sent straight to the login page because none of the landing-page work
  is pushed yet (the last pushed commit is `e329522`, where `/` was still the dashboard). Pushing fixes that.
- **Bug:** the pages treated "a session cookie exists" as "logged in", so an expired session showed "Open dashboard"
  and hid Log in and Sign up.

### Changed
- **New `components/AuthCta.tsx`** (client):
  - Renders the logged-out buttons first: nav "Log in" + "Sign up"; hero and closing sections "Sign up free" +
    "Log in".
  - Then calls `/api/v1/auth/me` once per page, shared by all buttons. Only a 200 swaps in "Dashboard" /
    "Open dashboard".
  - A failed or slow check leaves the login buttons in place.
- `SiteHeader`, the home page and the Platform page use it. They no longer read cookies on the server, so both pages
  are now static (`○` in the build) and load faster.

### Checked
- Typecheck and build pass.
- Server HTML has the `/login` and `/register` links with no cookie and with a stale cookie.
- In the browser: a valid session shows Dashboard / Open dashboard; an expired cookie shows Log in / Sign up.

---

## 2026-11-02 — Platform page

**Outcome:** A new public page at `/platform`, linked as "Platform" in the top bar and footer, explains how HookFlow
works in depth. The home page stays short.

### Changed
- **`app/platform/page.tsx`** (server component), with these parts:
  - Hero: "How HookFlow *delivers.*", plus pill links to each section.
  - 01 How it works: the animated `FlowDiagram` on a dark panel, then Accept / Fan out / Deliver / Record.
  - 02 Lifecycle: the five delivery states as cards, with a note on cancel and replay.
  - 03 Reliability: the retry rules with a backoff timeline; "saved before we say yes" (transaction, 202, lease,
    sweeper); idempotent ingestion.
  - 04 Security: the signed headers; signing, rotation grace (up to 7 days), SSRF/DNS rebinding, secrets at rest.
  - 05 Visibility: attempts with a replay marker; dashboard, replay, audit log, operations.
  - 06 Limits: a 12-item grid of the defaults.
  - A closing section over the photo: "Seen enough? *Send your first event.*"
- Every number matches the backend settings.
- **`components/SiteChrome.tsx`:** a shared `SiteHeader` (Platform / Developers / API reference, with the current
  page highlighted) and `SiteFooter`, used by both public pages. The home page now uses them too.
- **`middleware.ts`:** `/platform` is public.
- `.pf-*` styles, responsive at 1000, 760 and 520px. READMEs updated.

### Checked
- Typecheck and `next build` pass. Logged-out `/platform` → 200.
- Screenshots: full page (light), lifecycle in dark, phone width.
- Removed the misleading Delivered → Failed arrow in the lifecycle.

---

## 2026-11-02 — Leaner landing page

**Outcome:** The landing page is cut down to four parts: the photo hero, three short points, the code sample, and
the closing section. It was repeating itself.

### Changed
- **Removed:**
  - the "Delivery" diagram panel and example log, which repeated what the hero animation shows
    (`components/LiveLog.tsx` deleted; `FlowDiagram` is still used on the login page)
  - the four-number strip
  - the four long product sections with their visuals
  - the "Also included" list
  - the step list in the Developers section, replaced by one sentence
- **Added:** a three-column "points" row (Retries that back off / Signed requests / Every attempt, replayable), with
  serif titles and one or two lines each.
- About 80 CSS rules for the removed sections deleted.
- **Hero animation:** the beacon and endpoints moved toward the middle of the photo (orders, billing, notify), so they
  stay visible when tall screens crop the photo's sides. The labels are wider, so the text fits.

### Checked
- Typecheck and `next build` pass. Full-page screenshot, and the hero at 1280×1000.

---

## 2026-11-02 — Photo hero

**Outcome:** The landing page opens on a full-screen photo hero built from the user's `bg_image.jpg` (misty mountain
ridges), with signals animating across it. Nothing is committed yet.

### Changed
- **Images:** `frontend/public/landing/ridges-{900,1600,2600}.jpg` (61 KB, 171 KB and 488 KB), resized from the
  10000×6667, 6.5 MB original and served with `srcset`, so phones get the small one.
- **`components/HeroScene.tsx`** (client):
  - The photo fills the hero.
  - An SVG drawn in the photo's own 1200×800 coordinates (`preserveAspectRatio="xMidYMid slice"` matches
    `object-fit: cover`) keeps the animation pinned to the same peaks at any size.
  - The animation: a lime beacon on the near treeline sends glowing packets along dashed arcs to three distant peaks
    (orders, billing, notify). Each answers with a ping and a "200" chip; billing first pings red with "503", gets
    a retry packet, then turns green.
  - Gentle scroll parallax (photo at 0.32×, headline lifts and fades), and turned off for reduced motion.
- **Hero copy:** cream serif headline with "arrive." in lime, over a dark gradient on the trees. The lead starts
  "However far they have to go." Lime "Start for free" and frosted-glass "Log in" buttons.
- **Layout:** the diagram panel overlaps the bottom of the photo on wide screens and sits below it on narrower ones.
  The closing "Ship the feature" section uses the dark treeline from the same photo.
- **Dark mode** dims the photo and deepens the gradients.
- **Fix in `middleware.ts`:** the login redirect also caught static files, so logged-out visitors were sent to
  `/login` instead of receiving `/landing/*.jpg`. The matcher now skips any path with a file extension.

### Checked
- Typecheck and `next build` pass.
- Screenshots in light and dark at 1440px, the closing section, and phone width (where the panel used to cover the
  buttons; fixed).
- The image returns `200 image/jpeg` when logged out.

### Notes
- The original `bg_image.jpg` (6.5 MB) is still in the repo root and isn't used by the site. Delete it or add it to
  `.gitignore` before committing.

---

## 2026-11-02 — Visual redesign

**Outcome:** The site has its own look, replacing the generic one: ink and paper colours with one "signal lime"
accent, an editorial serif for headlines, and drawn icons. The landing page and login are rebuilt, and the dashboard
is restyled. Nothing is committed yet.

### Changed
- **Design tokens** (`globals.css`):
  - New light (paper `#f6f5f1`) and dark (ink `#0c0c0b`) palettes.
  - Primary buttons are ink (paper in dark mode). Links are olive in light mode and lime in dark.
  - `--signal` lime is used for highlights, the logo and the active-nav marker.
  - New `.ink` class for panels that are always dark.
- **Fonts** (`app/layout.tsx`, `next/font/google`, self-hosted at build time): Instrument Serif for headlines, Geist
  for the interface, Geist Mono for code.
- **Brand:** `components/Brand.tsx` (logo mark: a signal wave between source and destination) and a new
  `public/icon.svg`.
- **Icons:** `components/Icons.tsx`, drawn line icons replacing the Unicode glyphs in the sidebar.
- **Landing page** (`app/page.tsx`), rebuilt:
  - large serif headline with a lime underline that animates in
  - a dark "console" with `FlowDiagram` (pure SVG/SMIL: one event fans out to three endpoints; one fails with 503,
    is retried and succeeds) and `LiveLog` (an illustrative ticker)
  - a strip of four facts, all taken from the real settings
  - four numbered product rows, each with its own visual (backoff timeline, signed headers, attempts with a replay
    marker, durability sequence)
  - an "Also included" list
  - a Developers section with `CodeTabs` (curl / Node.js / Python, with copy)
  - a dark closing call to action, and footer
- **Login and sign-up:** a split screen, with the dark side showing the animated diagram, the tagline and facts, and
  a serif heading over the form. On phones, only the form shows.
- **Dashboard:** serif page titles, refined sidebar (active item with a lime bar), segmented control, buttons,
  inputs (focus ring), tables, tiles (hover lift) and a page fade-in.
- **Fix:** failed deliveries no longer say "Gave up after N attempts" twice.
- **Sidebar:** a "Back to website" link (home icon) at the bottom goes to the landing page.
- Motion respects `prefers-reduced-motion`: diagram packets are hidden and the log doesn't tick.

### Checked
- Typecheck and `next build` pass.
- Screenshots: landing (light and dark, top and lower sections), overview, endpoints and login.
- Fixed during review:
  - numbered lists broke one word per line (bold label and text were separate grid cells)
  - diagram labels overflowed their boxes
  - log timings wrapped onto a new line
  - the headline highlight sat too low

---

## 2026-11-02 — Landing page

**Outcome:** `/` is now a public landing page that explains HookFlow, with Log in and Get started buttons. The
dashboard overview moved to `/overview`. Nothing is committed yet.

### Changed
- `frontend/app/page.tsx` (new, server component), with these sections:
  - sticky nav
  - hero, with an example delivery timeline (503 → retry → 200)
  - six feature cards
  - "Live in three steps", with real curl and signature-verification snippets
  - final call to action, and footer
- Signed-in visitors (session cookie present) see "Open dashboard" in place of Log in / Get started.
- The copy only states what the product does; there are no made-up customers or numbers.
- `app/(dash)/page.tsx` moved to `app/(dash)/overview/page.tsx`. The sidebar and logo now link to `/overview`, and
  login goes to `/overview` by default.
- `middleware.ts`: `/` is public. Logged-out visits to any dashboard page redirect to `/login?next=...`.
- The logo on the login and register pages links back to the landing page.
- Landing styles (`.lp-*`) in `globals.css` use the existing colour variables, so light and dark both work.
  Responsive at 900px and 560px.
- READMEs updated.

### Checked
- `next build` and typecheck pass.
- Screenshots in dark, light and phone width.
- Logged-out `/` → 200; logged-out `/overview` → 307 to `/login?next=%2Foverview`; with a session cookie, `/` shows
  "Open dashboard".

### Notes
- An expired session cookie still shows "Open dashboard"; following it leads to the login page.
- Bookmarks to the old dashboard `/` now land on the landing page.

---

## 2026-11-01 — Dashboard improvements

**Outcome:** The dashboard is quieter, and it shows the Milestone 3 features: usage against limits, success rate and
latency, endpoint health, and system status. Nothing is committed yet.

### Changed
- **Deliveries table:** the explanation line under each row now appears only for failed, retrying and cancelled
  deliveries (or when the row is open), so successful rows are one line.
- **Overview:**
  - Defaults to the 24h range (hourly bars).
  - The "Get started" checklist hides once an event has been delivered, and has a Dismiss button.
  - Tiles: Events, Delivered, Retrying, Failed, Pending, Success rate, p95 response. The duplicate "Deliveries"
    tile was removed.
  - New **Usage** card: today's events against the daily quota, as a bar that turns amber at 80% and red at 100%,
    plus this minute's requests and reset countdowns.
- **Sidebar:** a status line: "All systems normal", "Deliveries delayed" (worker stale) or "Service problem". It
  polls `/health/ready` every minute, and the tooltip explains what it means.
- **Endpoints:** a "Health (24h)" column (Healthy / Degraded / Failing / No traffic, with success rate and the
  latest error) replaces "Max attempts", which is still on the detail page. The endpoint page shows health with a
  summary.
- **Backend:**
  - `GET /v1/usage`: today's count comes from the database, so it's right even for accounts that were unlimited.
  - `GET /v1/stats` gains `latency_ms` (p50/p95).
  - Endpoint list and detail include `health`.
  - `ratelimit.peek`.
  - Documented in `docs/api.md`.
- I'd said the sidebar stops partway down long pages. It doesn't: a real scroll shows it stays put, and the cut-off
  was only in the full-page screenshot.

### Checked
- `pytest`: 124 passed (6 new in `tests/test_dashboard_data.py`). Frontend typecheck and `next build` pass.
- Screenshots of the overview, endpoints and deliveries pages, with a healthy and a failing endpoint.
- Stopped the worker for 2+ minutes: `/health/ready` reported `stale` and the sidebar showed "Deliveries delayed".

### Left
- Filters (endpoint, event type, time range), search by ID, bulk replay, a light/dark toggle, copy buttons, a payload
  viewer, and a phone layout for tables.

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
