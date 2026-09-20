# Operations

Compose services:

| Service | Command | Role |
|---------|---------|------|
| timescaledb | TimescaleDB 16 | Ledger and queue |
| backend | `alembic upgrade head && uvicorn` | HTTP API |
| scheduler | `python -m app.worker.scheduler` | Enqueue basket × lead windows |
| collection-worker | `python -m app.worker.runner` | `FOR UPDATE SKIP LOCKED` collection |
| publisher | `python -m app.worker.publisher` | Quality + index publication |
| dashboard | Vite preview | Operator UI |

Health checks exist on every service. Collection workers keep one egress
identity and stop on 403/CAPTCHA. Scheduler interval:
`APIX_SCHEDULER_INTERVAL_SECONDS` (default 300 in mock; 86400 in the live
overlay). Live scheduling is opt-in (`--profile live-schedule`) and limited by
`APIX_SCHEDULER_SOURCE_NAMES` (EaseMyTrip in the overlay). Publisher interval:
`APIX_PUBLISHER_INTERVAL_SECONDS` (default 60).

CLI:

```bash
python -m app.cli run-index
python -m app.cli backtest --comparator cpi
```
