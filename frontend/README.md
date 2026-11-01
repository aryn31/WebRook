# HookFlow dashboard

Next.js 15 (App Router) + React 19 + TypeScript. Plain CSS, no UI libraries.

## Run locally

```bash
npm install
BACKEND_URL=http://localhost:8000 npm run dev   # http://localhost:3000
```

The browser only ever talks to the dashboard's own origin: `next.config.ts` rewrites
`/api/:path*` → `${BACKEND_URL}/:path*`, so `/api/v1/events` hits `${BACKEND_URL}/v1/events`
and the HttpOnly `hf_session` cookie set by the API works without CORS.

## Environment variables

| Variable | Default | When it's read | Purpose |
| --- | --- | --- | --- |
| `BACKEND_URL` | `http://localhost:8000` | **build time** (and dev server start) | Where `/api/*` is proxied. With `output: "standalone"` the rewrite is baked in at `next build`, so set it when building. In docker-compose use `http://api:8000`. |
| `NEXT_PUBLIC_API_PUBLIC_URL` | `http://localhost:8000` | build time (inlined) | Public API base URL shown in the copy-paste `curl` examples. |

## Scripts

- `npm run dev` – dev server on :3000
- `npm run build` – production build (standalone output)
- `npm run start` – serve the build
- `npm run typecheck` – `tsc --noEmit`

## Docker

```bash
docker build --build-arg BACKEND_URL=http://api:8000 \
             --build-arg NEXT_PUBLIC_API_PUBLIC_URL=http://localhost:8000 \
             -t hookflow-dashboard .
docker run -p 3000:3000 hookflow-dashboard
```

docker-compose example:

```yaml
  dashboard:
    build:
      context: ./frontend
      args:
        BACKEND_URL: http://api:8000
        NEXT_PUBLIC_API_PUBLIC_URL: http://localhost:8000
    ports: ["3000:3000"]
    depends_on: [api]
```

## Layout

- `lib/api.ts` – typed API client (types from `docs/api.md`), `ApiError`, redirect to `/login` on 401
- `lib/format.ts` – time formatting (local time, UTC on hover) and human-readable delivery explanations
- `middleware.ts` – redirects to `/login` when there is no `hf_session` cookie (the API's 401 is the real check). `/`, `/platform`, `/login` and `/register` are public
- `app/page.tsx` – public landing page (server component; shows "Open dashboard" when a session cookie exists)
- `app/(auth)` – login / register
- `app/(dash)` – overview, events, deliveries, endpoints, API keys, audit log
- `components/DeliveryTable.tsx` – delivery rows with a Replay action (when `replayable`) and attempt history with "Replayed" markers

## Pages

| Route | What it shows |
| --- | --- |
| `/` | Public landing page: photo hero, three key points, code sample, Log in / Get started |
| `/platform` | Public "Platform" page: how delivery works, the delivery lifecycle, reliability, security, visibility and limits |
| `/overview` | Overview: onboarding checklist, stat tiles, usage against limits, activity chart, recent failed deliveries. Login lands here |
| `/events`, `/events/[id]` | Events; event detail with payload, idempotency key, deliveries, per-delivery Replay and "Replay failed deliveries" |
| `/deliveries` | All deliveries with status tabs (e.g. `?status=failed`) and per-row Replay |
| `/endpoints`, `/endpoints/[id]` | Endpoints with 24h health; detail page with edit, secret reveal (audited, only on click), rotation with a grace period, test event, deliveries |
| `/api-keys` | Create / revoke API keys |
| `/audit-log` | Account audit trail, filter by `?action=` and `?resource_id=`, cursor pagination |
