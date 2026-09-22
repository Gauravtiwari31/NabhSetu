# Deployment

## Docker Compose

Services: TimescaleDB, API, scheduler, collection worker, index publisher, and
dashboard.

Safe default (`docker compose up --build`) is **mock** mode. For a live
presentation:

```bash
cp .env.example .env
docker compose -f docker-compose.yml -f docker-compose.live.yml up --build
```

The live overlay sets `APIX_DATA_MODE=live`, installs Chromium in the
collection-worker image, and leaves the scheduler off unless you pass
`--profile live-schedule`. Collect from the dashboard so a demo start does not
fire the full basket.

- API: http://localhost:8000
- Dashboard: http://localhost:5173
- Health: http://localhost:8000/health

The backend image runs `alembic upgrade head` then uvicorn. Environment:

- `APIX_DATA_MODE=live` (overlay) or `mock` (default compose)
- `APIX_EGRESS_MODE=direct`
- `APIX_DATABASE_URL=postgresql+asyncpg://apix:apix@timescaledb:5432/apix`
- `APIX_API_KEY` — required for collection, fares, sources, and `/v1` routes
- `APIX_SCHEDULER_SOURCE_NAMES` — optional live allowlist (default EaseMyTrip in the overlay)

Do not commit `.env`. The reference tree `Team_Tarang_SIH-26-main` is excluded
from the Docker build context.

## Local SQLite (tests / laptop without Postgres)

```bash
cd backend
pip install -e ".[test]"
pytest
```

SQLite startup uses `create_all`. Production Postgres schema is owned by Alembic.

## Secrets

Proxy URLs, API keys, and database passwords come from the environment. Egress
nodes store only an `endpoint_reference` such as `env:APIX_PROXY_A_URL`.

## Render

### Frontend (static site) — SPA routing

The dashboard is a single-page app: React Router owns `/collection`,
`/heatmap`, `/methodology` and the rest. Those paths exist only in the
browser, so a reload or a shared deep link asks Render for a file that was
never built, and Render answers with its own **Not Found** page. Only `/`
works, which is why the bug looks intermittent.

Fix it with a rewrite — not a redirect — so the URL is preserved and
`index.html` boots the router, which then reads the path:

| Setting | Value |
| --- | --- |
| Source | `/*` |
| Destination | `/index.html` |
| Action | **Rewrite** |

Set it under **Redirects/Rewrites** on the static site, or adopt the
blueprint in [`render.yaml`](../render.yaml), which declares the same rule.
Keep it as the last rule so real build assets still resolve first.

Build settings:

- Root directory: `frontend`
- Build command: `npm ci && npm run build`
- Publish directory: `dist`
- `VITE_API_BASE` — the API service URL
- `VITE_API_KEY` — must match `APIX_API_KEY` on the API

### Backend (web service)

- Root directory: `backend`, Docker runtime
- Health check path: **`/healthz`**

`/healthz` is the dependency-free liveness ping. `/health` is the real
status endpoint and reports `data_mode`, `is_simulated`, egress mode and
database reachability — point uptime monitors at `/healthz` and humans at
`/health`. Do not register another bare `/health` on the app: it is matched
before the router and hides the informative one.

Environment: `APIX_DATABASE_URL`, `APIX_API_KEY`, `APIX_DATA_MODE`,
`APIX_EGRESS_MODE`, `APIX_CORS_ORIGINS`.
