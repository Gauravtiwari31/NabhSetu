# SIH demonstration

Present **live mode**. Mock remains available as a labelled fallback when a
network or policy block would otherwise empty the room.

The dashboard banner is the source of truth:

- Green **LIVE MODE** — permitted sources only; no mock substitution.
- Amber **SIMULATED DATA** — fixture fares, never official measurements.
- Orange **POLICY DENIED** — a source was stopped without circumvention.

## Live presentation (preferred)

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -e ".[live]"
.\.venv\Scripts\python.exe -m playwright install chromium
$env:APIX_DATA_MODE = "live"
$env:APIX_EGRESS_MODE = "direct"
$env:APIX_API_KEY = "change-me"
$env:APIX_DATABASE_URL = "sqlite+aiosqlite:///./data/apix-live-demo.db"
.\.venv\Scripts\python.exe scripts\live_demo.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

`live_demo.py` collects **EaseMyTrip DEL-BOM T+7** with the identified research
User-Agent, then publishes APIx-T if at least `n_min` live quotes exist. A
CAPTCHA, robots denial, or empty page is stored as a typed status — not filled
with mock fares.

Dashboard walkthrough:

1. Green live banner.
2. Index trend — first published period is 100 with real coverage.
3. Route heatmap — uncovered basket routes stay blank.
4. Fare drill-down — INR, live label, no simulated flag.
5. Source health — EaseMyTrip approved; MMT/Cleartrip/ixigo denied.
6. Collection console — pick a permitted source; denied sources cannot be selected.
7. Methodology — Jevons / Young / omega / basket hash.
8. Back-test — `unavailable` until a checksummed DGCA/CPI file is imported.

Docker equivalent:

```powershell
docker compose -f docker-compose.yml -f docker-compose.live.yml up --build
```

Collect from the dashboard. Do not pass `--profile live-schedule` unless you
intend a daily EaseMyTrip basket run.

## Mock fallback

```powershell
docker compose up --build
```

Every number stays labelled simulated. Use this only to show the pipeline when
live sites are unreachable.

## Reading `denied` / `policy_denied` / `live`

A collection row such as DEL-BOM T+7 with status **denied**, result **policy_denied**, and label **live** is the governor stopping a disallowed source. It is not a scrape failure and is not filled with mock fares. Collect **EaseMyTrip** for a live success cell.

Full system explanation, setup, and this table: [Nabhsetu Project Usage Guide](Nabhsetu-Project-Usage-Guide.md) and [presentation](Nabhsetu-Project-Usage-Guide.pptx).

## What this demo is not

- It is not a 30-day official series.
- It is not a DGCA/CPI validation until official files are imported.
- It does not scrape MakeMyTrip, Cleartrip, ixigo, Yatra, or Goibibo.
