# Nabhsetu Project Usage Guide

**SIH 2026 · Problem Statement SIH26056**  
Real-Time Airfare Price Index for India — Ministry of Statistics and Programme Implementation (MoSPI)

This document explains the system that was built, how a fare becomes a published index point, how to run the completed setup, and how to read operator outcomes such as `policy_denied`. It is the companion to `docs/Nabhsetu-Project-Usage-Guide.pptx`.

---

## 1. What Nabhsetu is

Nabhsetu is a **compliance-first** platform that publishes the APIx airfare index. It:

1. Collects **permitted** public airfare observations from Indian airline and OTA websites.
2. Cleans, validates, and stores them in an **immutable** ledger with SHA-256 provenance.
3. Computes a versioned **APIx-T** price index at daily, weekly, and monthly frequencies for declared city-pairs and official lead windows **T+1 / T+7 / T+15 / T+30 / T+45**.
4. Serves the series to NSO/RBI-style consumers over authenticated `/v1` APIs (JSON, CSV, SDMX-JSON).
5. Shows operators the same numbers, coverage gaps, source health, and denials on a React dashboard.

It is a **greenfield** implementation at the repository root. The earlier prototype in `Team_Tarang_SIH-26-main/` is reference-only and is **not imported at runtime**.

Nabhsetu never fabricates fares, never solves CAPTCHAs, never spoofs a browser fingerprint, never bypasses login, never rotates IPs after a block, and never substitutes mock numbers for a live source that was denied.

---

## 2. What is built and working

| Layer | What shipped |
|-------|----------------|
| Domain | Typed `FareQuery`, money as `Decimal`, collection statuses, publication dispositions |
| Compliance | `ComplianceGovernor` ALLOW / DENY / REVIEW_REQUIRED before any collector |
| Acquisition | Public API → feed → static HTML → embedded JSON → Playwright network → Playwright DOM |
| Sources | 7 airline plugins + 6 OTA plugins + isolated `MockFareSource` |
| Egress | Direct identified research User-Agent; sticky session; failover only for dead nodes |
| Storage | SQLAlchemy ledger, TimescaleDB or SQLite, Alembic, immutability guards |
| Quality | Validation flags, Tukey/Hampel winsorisation, ACCEPTED / WINSORISED / QUARANTINED / EXCLUDED |
| Index | Pure-Decimal `apix_index` (Jevons, availability blend, Young, omega presets) |
| Workers | Scheduler, collection worker (`FOR UPDATE SKIP LOCKED`), publisher |
| APIs | Health, sources, jobs, fares, `/v1` index/coverage/elasticity/methodology/exports/backtest |
| Dashboard | Trend, heatmap, elasticity, fares, sources, collection, methodology, back-test |
| Live mode | Mock source disabled; EaseMyTrip collectable; denied OTAs visible but not selectable |
| Docker | Mock compose by default; `docker-compose.live.yml` overlay with Chromium worker |
| Evidence | Historical 1,823 EaseMyTrip fares (15/15 cells) plus the current live demo cell |
| Tests | Backend pytest (offline) and frontend vitest; tests never hit airline sites |

Honest gaps (not built): a 30-day production series, official DGCA/CPI file import in this environment, SIH portal video/template pack, written OTA permissions, production metrics/tracing.

---

## 3. End-to-end path: query → index

```
Dashboard / API / scheduler
        │
        ▼
   FareQuery  (DEL, BOM, T+7, observation date, source_id)
        │
        ▼
 ComplianceGovernor
   ALLOW  → lease + rate slot
   DENY / REVIEW_REQUIRED → job status denied, result policy_denied, stop
        │
        ▼
 SourceCapabilityRegistry ranks permitted adapters
        │
        ▼
 NetworkEgressManager  (direct, identified UA, one identity)
        │
        ▼
 Collectors  (waterfall; STOP on 403 / CAPTCHA / POLICY_DENIED)
        │
        ▼
 Canonical observations  (route, flight, fare INR, collector, hashes)
        │
        ▼
 Immutable ledger  (raw + normalised + provenance + supersedes_id)
        │
        ▼
 Quality gate  → ACCEPTED / WINSORISED only enter the index
        │
        ▼
 apix_index  Jevons elementary → availability blend → Young aggregation
        │
        ▼
 Published APIx-T  (daily / weekly / monthly) + coverage + CI
        │
        ├── /v1/index, /v1/exports, SDMX-JSON
        └── Dashboard (banner, trend, heatmap, fares)
```

**First published period is always 100.** Later days move relative to that base. Unmatched basket cells are **suppressed**, not imputed. Late entrants are **not chain-linked**. Coverage is reported honestly (a single DEL–BOM T+7 cell of a five-route × five-window basket is about **24%**).

---

## 4. How to read a collection row

The collection console is a ledger of jobs, not a scoreboard of “scrapes that worked”.

Example:

| When | Query | Status | Result | Label |
|------|-------|--------|--------|-------|
| 20 Sept 2026, 8:21 am | DEL-BOM T+7 | denied | policy_denied | live |

This row is **correct behaviour**.

| Field | Meaning |
|-------|---------|
| **When** | Job created (operator local time). |
| **Query** | City-pair and official lead window. Travel date = observation date + lead days. |
| **Status `denied`** | The job finished as a compliance stop (`JobStatus.DENIED`). No collector was allowed to continue. |
| **Result `policy_denied`** | `ComplianceGovernor` returned DENY or REVIEW_REQUIRED, or robots/terms/circuit forbade automation. Typed `CollectionStatus.POLICY_DENIED`. |
| **Label `live`** | `APIX_DATA_MODE=live`. The platform did **not** fill the gap with mock fares. |

Typical causes of `policy_denied` in live mode:

- The selected source has `automation_allowed=false` (MakeMyTrip, Cleartrip, ixigo, Yatra, Goibibo).
- `robots.txt` is unreadable, stale, or disallows the path (fail-closed).
- Terms review is `denied` or `review_required`.
- The source was previously restricted after HTTP 403 or CAPTCHA.
- Live mode was asked to use `MockFareSource` (mock is disabled when live).

What the system **does not** do after `policy_denied`:

- Retry with a different IP or User-Agent.
- Solve a CAPTCHA.
- Switch to mock fares for that source.
- Pretend the cell is missing because of a parser bug.

A later **success** on EaseMyTrip DEL–BOM T+7 is a different job: identified Playwright collection of public search cards, stored as `is_simulated=false`. Both rows can coexist. The published index uses only live, quality-accepted quotes from the live series.

Other result codes you may see:

| Result | Operator reading |
|--------|------------------|
| `success` | Canonical fares stored. |
| `no_results` | Page fetched; no matching itinerary cards. Circuit-neutral. |
| `network_error` / `temporary_failure` | Infrastructure; bounded retry, no rotate-on-block. |
| `rate_limited` | Back off; honour Retry-After. |
| `blocked` / `captcha_blocked` | Source stopped; recorded; no circumvention. |

---

## 5. Source catalog (reviewed 2026-09-20)

Identified User-Agent:

```
Nabhsetu-Research-Bot/0.1 (+https://www.mospi.gov.in; SIH26056 airfare index research)
```

### OTAs

| Source | Terms | Automation | Live collect? |
|--------|-------|------------|---------------|
| EaseMyTrip | No explicit automated-access ban; robots `Allow: *` | Approved | Yes — public search form |
| MakeMyTrip | Express ban on robots/scrapers | Denied | No |
| Cleartrip | Express ban + robots-disallowed search paths | Denied | No |
| ixigo | Ban on automated/non-human access | Denied | No |
| Yatra | Unclear; no research permission | Review required | No |
| Goibibo | Unclear | Review required | No |

### Airlines

Plugins exist for IndiGo, Air India, Air India Express, Akasa, SpiceJet, Star Air, and Alliance Air. Collection still fetches live `robots.txt` and fails closed. Yield is source-limited: many carrier sites return `no_results`, unreadable robots, or path blocks under identified traffic. **EaseMyTrip is the reliable permitted source for a live demonstration.**

Denied and review-required sources remain **visible** on Source health so judges can see the policy. They are **not selectable** in the collection console.

---

## 6. Index methodology (v1.0.0)

Config: `backend/config/method.yaml`, `basket.yaml`, `weights.yaml`. Engine: `backend/apix_index/` (pure Decimal; no pandas/numpy; no I/O).

- **Variant:** APIx-T (traveller-paid). **Basis:** book date.
- **Elementary index:** Jevons — geometric mean of matched price relatives.
- **Availability:** \(I_{adj} = I_{matched}^{A} \cdot I_{LAF}^{1-A}\). At \(A=1\) this equals the matched index.
- **Aggregation:** Young — weighted arithmetic mean of surviving cells, then routes, then lead windows.
- **Lead-time weights \(\omega_\tau\):** declared presets (`uniform`, `near_term`, `leisure`) over T+1/7/15/30/45. Default demo preset is **uniform**.
- **Basket:** DEL-BOM, BOM-DEL, DEL-BLR, BOM-BLR, DEL-HYD.
- **Carriers in seed weights:** 6E, AI, IX, QP, SG.
- **Weights source:** `equal_seed` until a checksummed DGCA traffic file is imported.
- **n_min:** 5 quotes in a cell or the cell is suppressed.
- **Uncertainty:** flight-block bootstrap, 90% interval.
- **Frequencies:** daily first; weekly and monthly by geometric aggregation.

Every published point is stamped with method, basket, and weights versions plus coverage, `n_matched`, and hashes.

---

## 7. Data, provenance, and quality

- Money is DECIMAL/NUMERIC, never float.
- Raw payloads, normalised observations, fare components, validation flags, and provenance links are **append-only**. Database triggers reject UPDATE/DELETE.
- Corrections insert a new row and set `supersedes_id`.
- Each entity carries a SHA-256 content hash. Publication runs store input and output hashes.
- Quality mapping: only `ACCEPTED` and `WINSORISED` quotes enter `apix_index`. Sold-out, stale, and excluded rows stay in the ledger as `QUARANTINED` / `EXCLUDED`.

---

## 8. Operator dashboard

URL: http://localhost:5173  
API: http://localhost:8000 · OpenAPI: http://localhost:8000/docs  
Restricted routes require header `X-API-Key`.

| Page | Role |
|------|------|
| Index trend | Latest APIx-T, coverage %, 90% interval, daily chart |
| Route heatmap | Route × T+ window; suppressed cells labelled; missing basket routes stay blank |
| Lead-time elasticity | Log-log elasticity across official windows |
| Fare drill-down | Latest fares in INR; `live` vs `simulated` chip |
| Source health | Terms, robots, automation allowed, circuits |
| Collection console | Route / lead / permitted source; Collect; Publish; job ledger |
| Methodology | Method notes, basket chips, route weights, publication hashes |
| Back-test | Official-file comparator; stays unavailable without DGCA/CPI files |

Persistent banner:

- Green **LIVE MODE** — permitted sources only.
- Amber **SIMULATED DATA** — mock fixtures; not measurements of Indian airfares.
- Orange **POLICY DENIED** — a recent job was stopped without substitution.

Live collection from the console can take up to about a minute (Playwright). Denied OTAs cannot be chosen. Pick **EaseMyTrip** for a live fare page.

---

## 9. Public APIs (NSO / RBI style)

All `/v1` routes and GET `/sources`, `/fares`, `/collection-jobs` require `X-API-Key`.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Mode, database, simulated flag |
| GET | `/v1/status` | Banner, latest run, blocked/enabled sources |
| GET | `/v1/index` | Headline series (`frequency=daily\|weekly\|monthly`) |
| GET | `/v1/index/cells` | Cell-level Jevons / LAF / suppression |
| GET | `/v1/coverage` | Basket coverage diagnostics |
| GET | `/v1/elasticity` | Lead-window elasticities |
| GET | `/v1/methodology` `/v1/basket` `/v1/weights` `/v1/provenance` | Method disclosure |
| GET | `/v1/exports/index.csv` `/v1/exports/index.sdmx.json` | Machine exports |
| POST | `/v1/index/publish` | Run quality + engine |
| GET | `/v1/backtest` | Official-file comparison |
| POST | `/collection-jobs` | Collect one query (sync) |
| GET | `/fares/latest` | Canonical observations |

Live publications set `is_simulated=false`. Mock publications set it true and attach a simulated notice.

---

## 10. Setup completed

### 10.1 Laptop live demo (what is running for presentation)

Prerequisites: Python 3.12+, Node 22+, Playwright Chromium.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[live,test,docs]"
python -m playwright install chromium

$env:APIX_DATA_MODE = "live"
$env:APIX_EGRESS_MODE = "direct"
$env:APIX_API_KEY = "change-me"
$env:APIX_DATABASE_URL = "sqlite+aiosqlite:///./data/apix-live-demo.db"
$env:APIX_PLAYWRIGHT_TIMEOUT_MS = "60000"
$env:APIX_MAX_ADAPTER_RETRIES = "0"

python scripts\live_demo.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

`scripts/live_demo.py` collects **EaseMyTrip DEL–BOM T+7** for **today’s** observation date and publishes if at least `n_min` live quotes exist. Verified on 2026-09-20: **130 live observations**, **0 simulated**, APIx-T **100.00**, coverage **24%**, run hashes stored on the methodology page.

### 10.2 Docker live overlay

```powershell
Copy-Item .env.example .env
docker compose -f docker-compose.yml -f docker-compose.live.yml up --build
```

- TimescaleDB, API (Playwright-capable), collection worker (Chromium), publisher, dashboard.
- `APIX_DATA_MODE=live`. Mock source is seeded **disabled**.
- Scheduler is **off** unless you pass `--profile live-schedule` (daily EaseMyTrip basket). For a demo, collect from the dashboard so the full basket is not fired on boot.

### 10.3 Mock fallback (no network)

```powershell
docker compose up --build
```

Or local SQLite with `APIX_DATA_MODE=mock`. Every fare and index point is labelled simulated. Use this only when live sites are unreachable. **Never mix mock quotes into a live published series** — the publisher reads `simulated=` from the data mode.

### 10.4 Environment that matters

| Variable | Live demo value | Role |
|----------|-----------------|------|
| `APIX_DATA_MODE` | `live` | Disables mock; no simulated substitution |
| `APIX_EGRESS_MODE` | `direct` | No proxy pool |
| `APIX_API_KEY` | matches `VITE_API_KEY` | Restricts jobs, fares, `/v1` |
| `APIX_DATABASE_URL` | SQLite or Postgres | Ledger |
| `APIX_SCHEDULER_SOURCE_NAMES` | `EaseMyTrip` in overlay | Live allowlist |
| `APIX_IDENTIFIED_USER_AGENT` | Nabhsetu-Research-Bot/0.1 … | Must not spoof a consumer browser |

---

## 11. Operator sequence (live)

1. Confirm `/health` → `data_mode=live`, `is_simulated=false`.
2. Open Source health — EaseMyTrip approved; MMT/Cleartrip/ixigo denied.
3. Collection console — source **EaseMyTrip**, route DEL-BOM, T+7 → **Collect**.
4. If the row is `success` / `live`, open Fare drill-down (INR, live chip).
5. **Publish index** (or rely on the publisher worker).
6. Index trend shows 100.00 on the first period and honest coverage.
7. Heatmap shows DEL-BOM T+7; other basket cells stay blank.
8. Methodology shows method v1.0.0 and input/output hashes.
9. Back-test remains **unavailable** until a checksummed DGCA/CPI file is imported.

If step 3 returns `denied` / `policy_denied` / `live`, **that is the demonstration of compliance**. Switch the source to EaseMyTrip (if it was an airline or denied OTA) rather than “fixing” the denial with mock data.

---

## 12. Evidence already on disk

| Artifact | Content |
|----------|---------|
| `backend/data/ota-policy-review.json` | Live robots/terms review |
| `backend/data/ota-live-run-report.json` | 2026-09-20 OTA matrix: 1,823 real EaseMyTrip fares, 15/15 cells, 0 simulated, denied OTAs recorded as policy denials |
| `backend/data/live-demo-report.json` | One-cell live demo: EaseMyTrip DEL-BOM T+7, observation count, publication |
| `backend/data/apix-live-demo.db` | SQLite ledger for the presentation API |
| `docs/ota-source-review.md` | Human-readable OTA decisions |

---

## 13. Tests

```powershell
cd backend
python -m pip install -e ".[test]"
pytest
```

```powershell
cd frontend
npm test
```

Tests use fixtures and in-memory SQLite. They never contact airline or OTA websites. Circumvention capabilities are guarded by `tests/test_no_circumvention.py`.

Regenerate this presentation after editing the generator:

```powershell
cd backend
python -m pip install -e ".[docs]"
python scripts\generate_usage_presentation.py
```

---

## 14. Official files (when available)

Never paste invented DGCA/CPI numbers.

```powershell
cd backend
python -m app.cli import-dgca path\to\dgca.csv --source-url https://official.example/file
python -m app.cli import-cpi path\to\cpi.csv --source-url https://official.example/file
python -m app.cli run-index
python -m app.cli backtest --comparator dgca
```

Insufficient overlap → `unavailable` or `not_reportable`. Record real checksums in `docs/30-day-run-manifest.md` after a genuine window.

---

## 15. What is still missing from a submittable SIH pack

The platform is **demonstrable**. These items are **not** done:

1. Continuous **30-day live series** (a one-cell or one-day collect is not a month of APIx-T).
2. **Checksummed DGCA/CPI files** in this environment — back-test stays unavailable.
3. **SIH portal pack** — idea PPT in their template, 3–5 minute video, team ID, public GitHub URL, consent.
4. **Full-basket live coverage** — five routes × five windows; a demo cell is ~24%.
5. **Airline-site yield** under identified, robots-respecting collection.
6. **Written permission** for denied OTAs.
7. **CI Playwright E2E** of the dashboard against a live site.
8. **Production metrics/tracing** (structured logs exist).
9. A **filled** 30-day run manifest.

Do not claim NSO/RBI production readiness or a completed official back-test until those files and the 30-day window exist.

---

## 16. Repository map

| Path | Role |
|------|------|
| `backend/app/` | API, governor, collectors, storage, workers |
| `backend/apix_index/` | Decimal APIx-T mathematics |
| `backend/config/` | Method, basket, weights YAML |
| `backend/scripts/` | Live policy review, matrix collect, `live_demo.py`, this PPT generator |
| `backend/tests/` | Offline automated verification |
| `frontend/` | Operator dashboard |
| `docker-compose.yml` | Mock stack |
| `docker-compose.live.yml` | Live overlay + Chromium |
| `docs/` | Architecture, methodology, compliance, this guide |
| `Team_Tarang_SIH-26-main/` | Reference only |

Further reading: `docs/architecture.md`, `docs/acquisition-engine.md`, `docs/compliance.md`, `docs/index-methodology.md`, `docs/ota-source-review.md`, `docs/sih-demo.md`, `docs/deployment.md`.
