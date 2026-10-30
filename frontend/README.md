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
- `middleware.ts` – redirects to `/login` when there is no `hf_session` cookie (the API's 401 is the real check)
- `app/(auth)` – login / register
- `app/(dash)` – overview, events, deliveries, endpoints, API keys
