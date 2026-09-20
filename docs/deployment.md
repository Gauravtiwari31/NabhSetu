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
