# APIx — Real-time Airfare Price Index for India

**SIH 2026 · PS 26056 · MoSPI, Data Informatics & Innovation Division**

A daily, route-level, lead-time-resolved airfare price index built on the same
index-number machinery MoSPI adopted for CPI 2024 — Jevons at the elementary
level, Young/Modified Laspeyres above it — so it plugs into COICOP sub-class
07.3.3 without a methodological argument.

---

## Zero to an index number in four commands

```bash
pip install -r requirements.txt

python cli.py init                          # schema + seed the basket, carriers, charges
python cli.py load-cpi --dir ../Datasets    # official CPI comparator + nowcast target
python cli.py backfill --days 240 --end 2026-07-31   # quote history (simulator rung)
python cli.py index                         # compute and publish the index family
python cli.py serve                         # dashboard on :8000, API docs at /docs
```

The backfill window deliberately ends **2026-07-31** so the monthly APIx series
overlaps the CPI comparator, which runs to July 2026. A window that does not
overlap makes the back-test unrunnable.

No database server, no API key, no network. `init` + `backfill` + `index` takes
about nine minutes on a laptop and the demo then runs entirely offline.

```bash
python cli.py status        # what is in the store
python cli.py elasticity    # fit eta(tau), report tau*
python cli.py backtest      # agreement statistics vs the CPI comparator
python cli.py nowcast       # fit the CPI transport bridge model
python cli.py verify        # hash chain + the full data-quality contract
python cli.py reproduce     # recompute every published number and diff
python -m pytest            # 117 tests
make report                 # regenerate the PDF test & review report
```

---

## Read this before demoing

**The data is synthetic.** `backfill` runs the rung-0 deterministic simulator,
not a collector. Every quote is stamped `is_synthetic = 1`, every API response
carries a `SYNTHETIC` field, and the dashboard shows a banner. The numbers
demonstrate the *method*. They are **not** a measurement of Indian airfares, and
presenting them as one would be the single worst thing you could do with this
repository.

To collect real fares, key a rung-1 licensed API in `config/sources.yaml` and set
its credential environment variable. The adapters are stubbed; the ladder,
governor, ledger and index engine around them are not.

---

## The three things that actually differentiate this

### 1. The reframe: CPI 2024 already collects airfares online

The PS background describes manual price collection. That describes the **CPI
2012 series, retired 12 February 2026**. Under CPI 2024, MoSPI's own FAQ states
airfares are collected through well-known online platforms, weekly, across twelve
online markets. A MoSPI evaluator knows their own methodology; a team that opens
with "currently MoSPI collects airfares manually" has lost the room.

So APIx argues a **delta**, not a replacement. `GET /v1/methodology` states it
machine-readably; `Part 1 §2` of the project document has the table.

### 2. The PS contains an internal contradiction, resolved deliberately

It asks the system to handle *"dynamic CAPTCHAs, anti-bot measures, IP rotation"*
and, in the same sentence, to remain *"compliant with the robots.txt and terms of
service of source websites."* **These cannot both be satisfied.** A CAPTCHA is a
technical access control, so defeating it is unauthorised access under s.43 of
the IT Act, 2000.

APIx inverts the priority — compliance is the hard constraint, coverage is the
optimisation target — and encodes that in code, not in prose:

| Enforced where | What it does |
|---|---|
| `apix_collect/politeness.py` | robots.txt as binding policy (**fails closed** if unreadable), per-host token bucket, **one** in-flight request per host, exponential backoff with jitter, circuit breaker that escalates to a human, instant kill switch |
| `apix_collect/provenance.py` | append-only ledger, `h_n = SHA256(h_{n-1} ‖ canonical(record_n))` — tamper-evident |
| `apix_store/schema.sql` | `dim_source.legal_basis` is `NOT NULL`; DB triggers make quotes and the ledger immutable |
| `tests/…::test_no_circumvention_code_exists_anywhere_in_the_package` | asserts the *capability is absent*, not merely unused — add a CAPTCHA solver and CI fails |

A request blocked by robots.txt is **never issued** and is recorded as
`ROBOTS_BLOCKED`. That is the point: we can prove months later what we did *not*
do.

> **Rehearsed answer.** *"You haven't done CAPTCHAs."* — Correct, and
> deliberately. The same paragraph also requires ToS and robots.txt compliance,
> and those are mutually exclusive. We resolved the contradiction the way a
> government statistical product has to. Here is the coverage ledger, here is
> the variance that coverage implies. A ministry can deploy this on Monday.

### 3. Sold-out inventory is a price signal, not missing data

A cell offers fares at ₹4,000 / ₹6,000 / ₹9,000. A surge closes the two cheap
buckets. The ₹9,000 quote **has not changed price**, so a strictly matched index
reports *zero inflation* through exactly the episode consumers experience as a
fare explosion. This is the most defensible criticism of a naive fare index.

APIx blends the matched index with a lowest-available-fare index, controlled by
the availability ratio `A`:

```
I_adj = (I_matched)^A · (I_LAF)^(1−A)
```

Continuous, monotone, and at `A = 1` it reduces **exactly** to the matched index
— so nothing changes in the normal case. Both properties are asserted in tests,
and verified on the full 120-day dataset: **0 violations across 114 periods
where A = 1**.

Live, from `GET /v1/availability/series?route=DEL-BOM&apw_days=7`:

| period | matched | LAF | adjusted | A |
|---|---|---|---|---|
| 2026-08-28 | 107.67 | 107.58 | **107.67** | 1.000 |
| 2026-08-31 | 127.74 | 183.09 | **147.52** | 0.600 |
| 2026-09-04 | 108.03 | 107.36 | **108.03** | 1.000 |

The naive line understates the surge by ~20 index points. That is the ninety
seconds of demo the whole methodology argument rests on.

---

## Architecture

```
config/*.yaml ──┐
                ▼
   SOURCE LADDER (rung 0 simulator → 1 licensed API → 3 permitted page)
                │   every fetch passes the POLITENESS GOVERNOR
                ▼   every fetch writes to the HASH-CHAINED LEDGER
   Stage 0b  decompose   base = (total − UDF − ASF − RCS − CF) / (1 + GST)
   Stage 0c  clean       Tukey 3×IQR + Hampel MAD + longitudinal jump
   Stage 0d  disposition ACCEPTED · WINSORISED · EXCLUDED · QUARANTINED
                ▼
   SQLite (→ PostgreSQL 16 + TimescaleDB unchanged in shape)
                ▼
   DATA QUALITY CONTRACT ── BLOCK failures stop publication
                ▼
   apix_index  ── PURE. No I/O, no clock, no network.
        compute(quotes, weights, config) -> IndexResult
                ▼
   FastAPI (REST + SDMX-JSON) ──▶ dashboard
```

### The index engine is pure by design

`apix_index` has no database, no network, no clock, and no randomness beyond a
seeded bootstrap. That purity is what makes it unit-testable against worked
examples and what lets MoSPI's Price Statistics Division run it on **their** data
without adopting the rest of the stack.

```python
from apix_index import compute, MethodConfig, WeightSet
result = compute(quotes_df, weights, MethodConfig(basis="travel", variant="T"))
```

The vectorised engine is validated against an independently written, deliberately
naive implementation of the Part 4 arithmetic: **max absolute difference 0.0**.

---

## The computation, stage by stage

| Stage | Operation | Rule |
|---|---|---|
| 0a | Validity gates | Deterministic rejects; plausibility bounded by great-circle distance |
| 0b | Decompose | Administered charges from effective-dated SCD tables, **never scraped**; base is the residual, reconciled to within ₹1 |
| 0c | Outliers | Tukey **3×**IQR (not 1.5 — fares are legitimately dispersed) + Hampel \|z\|>3.5, in log space |
| 0d | Disposition | Winsorise at the fence; **never delete** |
| 1 | Elementary | Jevons over matched κ within cell `g = (route, carrier, τ)`; suppress below `n_min = 5` |
| 1b | Availability | `I_adj = I_matched^A · I_LAF^(1−A)` |
| 1c | De-seasonalise | 7-day **centred geometric** MA — annihilates a weekly cycle *exactly* (asserted in tests) |
| 2 | Carrier | `φ_c\|r ∝ S_c · F_c,r · Seats · PLF` |
| 3 | Route | `w_r` from AAI/DGCA sector traffic, **or PSD-supplied** |
| 4 | Lead time | `ω_τ` — a declared policy parameter, three presets |
| 7 | Uncertainty | Delta-method SE + **flight-block** bootstrap, seeded |

**The matching key.** Two quotes are the same product iff they agree on
`(route, carrier, τ, flight_number, fare_family, cabin, stops)`. Matching on
`flight_number` rather than departure date tracks *the same flight in the
schedule* across weeks — the airline analogue of tracking the same SKU in a shop.

**The day-of-week trap.** Hold τ fixed and advance t by one day, and the
departure date advances too — so a Tuesday-departure observation becomes a
Wednesday one. Fares are strongly day-of-week dependent, so a naive daily index
reports pure day-of-week variation as inflation. The 7-day centred geometric MA
removes it exactly. State this unprompted; it is what a MoSPI statistician probes
for.

---

## Honest weaknesses, stated up front

**ω_τ is the single largest judgement call in the index.** The weights over
advance-purchase windows should be the distribution of actual booking lead times
of Indian travellers. That distribution is not public — DGCA asked airlines for
ticket-level data in December 2024 and the Federation of Indian Airlines refused
on commercial-confidentiality grounds. APIx therefore treats ω_τ as a **declared,
versioned policy parameter**, ships three named presets, publishes under all
three, and the spread between them *is* the sensitivity analysis. It does not
pretend the number is measured. `GET /v1/methodology` says so in the payload.

**Coverage under the compliance constraint is lower than a scrape-everything
team's.** The demo covers 12 of 60 basket routes — 20% by route count, **59.3% by
traffic weight**, and 12/12 of the sectors the PS names. `/v1/coverage` reports
against the **full** basket and lists the uncollected routes rather than
renormalising the gap away.

**Weekly frequency `F_c,r` is proxied by national carrier share**, since per-route
frequency is not published. Marked `[VERIFY]` in `config/carriers.yaml`. With the
prior correctly off, φ reproduces published DGCA passenger shares to within 1.3pp
— which is the sanity check to run and quote.

**Airfare is a small CPI weight.** Transport is 8.796% of combined CPI 2024 and
air fare is a fraction of that. Do not sell APIx as moving headline inflation.
Sell it as methodological infrastructure MoSPI can reuse for hotels, cabs and the
twelve online markets it just added — airfare is the *hardest* case, because of
dynamic pricing, perishable inventory and availability censoring.

Every figure marked **`[VERIFY]`** in `config/` moves and must be re-pulled from
the primary source before it is quoted on stage.

---

## The CPI reference data, and what it can honestly support

`python cli.py load-cpi` normalises the MoSPI CPI workbooks into
`fact_cpi_reference` — 387,743 rows across three base years:

| File | Base | Span | Deepest level |
|---|---|---|---|
| `cpi_96.xlsx` | 2024 | 2025-01 → 2026-07 | **division** — `Transport` |
| `cpi_554.xlsx` | 2012 | 2013-01 → 2025-12 | **subgroup** — `Transport and Communication` |
| `cpi_544.xlsx` | 2010 | 2011-01 → 2014-12 | **subgroup** — `Transport and Communication` |
| `CPI updated_July_2026_Dashboard…xlsx` | — | — | *skipped: pivoted presentation table, no classification columns* |

**There is no air-fare item index in any of them.** `cpi.find_air_fare_item()`
returns empty, and the back-test says so rather than quietly substituting the
aggregate. For the item series proper you need an item-level extract from
<https://cpi.mospi.gov.in> (COICOP sub-class 07.3.3).

This matters for interpretation: Transport also contains road fuel, vehicle
purchase, rail fares and communication, and air fare is a small slice of it. So
**agreement is diluted by construction** — a weak correlation against Transport
is the expected result, not evidence APIx is broken. Every result row carries
the comparator level so nobody can quote a number without knowing what it
compared against.

### There is no "model training" in the index itself

APIx is deterministic index-number arithmetic. Nothing in `apix_index` is
trained, and CPI data is not training data for it. The genuinely *fitted* models
are two, and both live in `apix_pipeline`:

- **`elasticity.py`** — the η(τ) surface. Trained on the fare quotes themselves.
  Already working: recovers τ\* = 27.0 days against the simulator's true 26.0.
- **`nowcast.py`** — the CPI transport bridge. *This* is what the CPI data feeds.

### The nowcast bridge refuses to lie

`nowcast.fit()` returns `interpretable: False` with reasons attached, rather than
a plausible-looking coefficient table, when either guard trips:

1. **Too few observations.** CPI 2024 starts in 2025 and y-o-y inflation costs a
   further 12 months, leaving ~7 usable points. A bridge with lags and an ATF
   control cannot be estimated from that. `MIN_OBS_ABSOLUTE = 24`, and at least
   8 observations per parameter.
2. **Synthetic regressor.** Regressing real CPI on simulator output estimates the
   relationship between real inflation and a random number generator. The
   arithmetic succeeds; the coefficient means nothing.

Out-of-sample evaluation is **expanding-window, never a random split** — a random
split on a time series leaks the future into the past and is the most common way
a nowcast gets accidentally overstated. Granger causality declines to test when
the sample gives it no power, and says "cannot tell" rather than "no
relationship".

The harness is complete and tested. It will produce a real answer the day enough
real history exists; until then it declines, which is the correct output.

## Test & review report

A full code review and test run is rendered to
[`reports/APIx_Test_and_Review_Report.pdf`](reports/APIx_Test_and_Review_Report.pdf)
(17 pages). Regenerate it with `make report` — every number in it is read from
`reports/evidence.json`, which is produced by actually executing the thing it
reports on.

| | |
|---|---|
| Tests | **117 passed**, 0 failed |
| Statement coverage | **88.2%** over 1,985 statements |
| Engine vs independent reference | max abs difference **0.000e+00** |
| Reproducibility | **zero differences** across 23,823 published numbers |
| Governance | hash chain intact; 10/12 quality checks pass, 2 expected ALERTs |
| API | 34/34 routes and negative cases pass |

The review found six defects. One was a genuine correctness bug:

> **F1 — winsorisation was silently discarded.** `clean()` capped an outlier only
> in an in-memory column; the store kept `total_fare` and the index recomputed
> prices from it. A quote labelled `WINSORISED` therefore entered the index at
> its **full uncapped value** — a ₹45,000 parse artefact in a ₹5,000 cell would
> have entered at ₹44,701 instead of the capped ₹5,652, while the audit trail
> asserted it had been capped. Fixed with a persisted `total_fare_capped`
> column (the observation stays immutable), an idempotent migration, and four
> regression tests.

The other five: no chain-linking for late entrants (documented, pinned by a
test); a docstring claiming test coverage that did not exist (test added);
`elasticity.py` at **0% coverage** (19 tests added, now 95.4%); two declared-but-
never-written tables; and dead code. All are listed with evidence in §2 of the
report.

## Reproducibility

```
$ python cli.py reproduce
  published numbers      11925
  recomputed numbers     11925
  unmatched keys         0
  numbers differing      0
  max abs difference     0

  ZERO DIFFERENCES
```

This works because the engine is pure, the bootstrap is seeded, and index ids are
deterministic UUID5 hashes of `(code, period, frequency, basis, preset,
method_version, weights_version)`. Change the method and old numbers stay
reproducible under the old version.

---

## API

| Endpoint | Returns |
|---|---|
| `GET /v1/index` | Headline series. `variant` B/T/A, `frequency`, `basis` book/travel, `omega_preset`, `format` json/**sdmx-json**/csv |
| `GET /v1/index/routes/{route}` | Route-level index |
| `GET /v1/index/apw/{tau}` | A single advance-purchase window |
| `GET /v1/elasticity` | η(τ), τ*, coefficients, cluster-robust SEs |
| `GET /v1/components` | Base / YQ / UDF / ASF / RCS / GST / convenience fee |
| `GET /v1/availability` | A_g(t) |
| `GET /v1/availability/series` | **matched vs LAF vs adjusted** — the three lines |
| `GET /v1/backtest` | **Agreement statistics vs the CPI comparator** |
| `GET /v1/cpi` | The loaded official CPI reference series |
| `GET /v1/coverage` | Coverage ledger + source ladder + governance state |
| `GET /v1/provenance/{index_id}` | Full audit chain behind one published number |
| `GET /v1/methodology` | Machine-readable method, weights, and collection policy |

SDMX-JSON is a deliberate credibility play: it is what statistical agencies and
central banks actually consume.

---

## Layout

```
cli.py                          init · backfill · index · elasticity · verify · reproduce · serve
config/
  method.yaml                   formulae, thresholds, omega presets      [VERIFY]
  basket.yaml                   30 pairs -> 60 directional routes        [VERIFY]
  carriers.yaml                 DGCA share, PLF, seats                   [VERIFY]
  charges.yaml                  UDF/ASF/RCS/GST SCD seed                 [VERIFY]
  sources.yaml                  the source ladder + politeness policy
  psd_weights.yaml              (optional) PSD-supplied weights — overrides everything
src/apix_index/                 PURE index engine — no I/O
src/apix_collect/               ladder, politeness governor, provenance ledger, simulator
src/apix_pipeline/              decompose, clean, quality contract, elasticity, index run
src/apix_store/                 schema.sql + repository
src/apix_api/                   FastAPI, REST + SDMX-JSON
dashboard/index.html            self-contained SPA, no build step
tests/                          117 tests
```

## Security and governance

- **No personal data is collected, stored or inferred.** Fares are not personal
  data, so the DPDP Act, 2023 does not attach — a design property, not a
  disclaimer.
- Quotes and the provenance ledger are immutable, enforced by database triggers
  rather than by convention. Corrections are new rows with `supersedes_quote_id`.
- Every configuration change to weights, basket or method version is audited with
  the operator identity.
- No credential is stored in the repository; rung-1 sources read from the
  environment.
- A single kill-switch flag disables any host instantly.
