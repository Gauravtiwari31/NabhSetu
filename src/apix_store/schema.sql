-- APIx store schema (Part 5, section 3).
--
-- SQLite is the MVP target: the whole point of the demo is that it runs on a
-- cold laptop with no services. The schema is deliberately written so the
-- production move to PostgreSQL 16 + TimescaleDB is a DDL translation and not
-- a redesign: fact_fare_quote becomes a hypertable on collected_at_utc with
-- 1-day chunks, and the two rollup views become continuous aggregates.
--
-- Two disciplines are enforced here rather than by convention:
--   1. QUOTES ARE IMMUTABLE. No UPDATE on fact_fare_quote, ever. Corrections
--      are new rows carrying supersedes_quote_id. A mutable price table is
--      disqualifying for official statistics.
--   2. PROVENANCE IS APPEND-ONLY AND HASH-CHAINED, so the collection history
--      is tamper-evident.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- dimensions

CREATE TABLE IF NOT EXISTS dim_route (
    route_sk        INTEGER PRIMARY KEY,
    route           TEXT NOT NULL UNIQUE,      -- 'DEL-BOM', directional
    origin_iata     TEXT NOT NULL,
    dest_iata       TEXT NOT NULL,
    origin_city     TEXT,
    dest_city       TEXT,
    gc_distance_km  REAL,
    stratum         TEXT NOT NULL,
    is_rcs          INTEGER NOT NULL DEFAULT 0,
    in_ps_list      INTEGER NOT NULL DEFAULT 0,
    annual_pax      INTEGER,
    weight_wr       REAL,
    basket_version  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_carrier (
    carrier_sk      INTEGER PRIMARY KEY,
    iata            TEXT NOT NULL UNIQUE,
    icao            TEXT,
    name            TEXT NOT NULL,
    model           TEXT,                      -- LCC | FSC
    national_share  REAL,
    plf             REAL,
    avg_seats       INTEGER,
    as_of_month     TEXT
);

-- The Source Ladder lives here. ladder_rung and legal_basis are NOT NULL
-- because a quote whose legal basis is unrecorded must not be storable.
CREATE TABLE IF NOT EXISTS dim_source (
    source_sk           INTEGER PRIMARY KEY,
    name                TEXT NOT NULL UNIQUE,
    type                TEXT NOT NULL,          -- simulator | licensed_api | public_page
    ladder_rung         INTEGER NOT NULL,
    legal_basis         TEXT NOT NULL,
    tos_url             TEXT,
    robots_snapshot_id  TEXT,
    enabled             INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dim_date (
    date_sk             TEXT PRIMARY KEY,       -- 'YYYY-MM-DD'
    dow                 INTEGER NOT NULL,       -- 0 = Monday
    is_weekend          INTEGER NOT NULL DEFAULT 0,
    is_holiday          INTEGER NOT NULL DEFAULT 0,
    festival_name       TEXT,
    is_long_weekend     INTEGER NOT NULL DEFAULT 0,
    school_vacation_flag INTEGER NOT NULL DEFAULT 0
);

-- ----------------------------------------------- slowly-changing dimensions

CREATE TABLE IF NOT EXISTS scd_airport_charges (
    id                      INTEGER PRIMARY KEY,
    airport_iata            TEXT NOT NULL,
    udf_domestic            REAL NOT NULL,
    asf                     REAL NOT NULL,
    effective_from          TEXT NOT NULL,
    effective_to            TEXT,               -- NULL = currently in force
    source_notification_url TEXT
);
CREATE INDEX IF NOT EXISTS ix_scd_charges ON scd_airport_charges(airport_iata, effective_from);

CREATE TABLE IF NOT EXISTS scd_tax_rate (
    id               INTEGER PRIMARY KEY,
    cabin            TEXT NOT NULL,
    gst_rate         REAL NOT NULL,
    effective_from   TEXT NOT NULL,
    effective_to     TEXT,
    notification_ref TEXT
);
CREATE INDEX IF NOT EXISTS ix_scd_tax ON scd_tax_rate(cabin, effective_from);

-- ------------------------------------------------------------------- facts

CREATE TABLE IF NOT EXISTS fact_fare_quote (
    quote_id             TEXT PRIMARY KEY,      -- uuid
    run_id               TEXT NOT NULL,
    collected_at_utc     TEXT NOT NULL,
    collected_at_ist     TEXT NOT NULL,         -- both stored, never derived on read
    collected_date       TEXT NOT NULL,         -- IST calendar date, the index period
    route                TEXT NOT NULL REFERENCES dim_route(route),
    carrier              TEXT NOT NULL REFERENCES dim_carrier(iata),
    source               TEXT NOT NULL REFERENCES dim_source(name),
    flight_number        TEXT NOT NULL,
    departure_date       TEXT NOT NULL,
    departure_time_local TEXT,
    arrival_time_local   TEXT,
    apw_days             INTEGER NOT NULL,
    cabin                TEXT NOT NULL,
    fare_family          TEXT NOT NULL,
    rbd                  TEXT,
    stops                INTEGER NOT NULL DEFAULT 0,
    currency             TEXT NOT NULL DEFAULT 'INR',
    total_fare           REAL,       -- the OBSERVED total, never modified
    -- The value the INDEX should use. NULL unless disposition = 'WINSORISED',
    -- in which case it is the observed total capped at the Tukey fence. Kept
    -- as a separate column so the observation stays immutable while the
    -- pipeline's treatment of it is recorded rather than merely labelled --
    -- `disposition` says what was DONE, and this is the doing.
    total_fare_capped    REAL,
    base_fare            REAL,
    yq_yr                REAL,
    udf                  REAL,
    asf                  REAL,
    rcs_levy             REAL,
    gst                  REAL,
    convenience_fee      REAL,
    seats_remaining_shown INTEGER,
    is_sold_out          INTEGER NOT NULL DEFAULT 0,
    is_synthetic         INTEGER NOT NULL DEFAULT 0,
    quality_flag         TEXT,                  -- what the detector FOUND
    disposition          TEXT NOT NULL,         -- what the pipeline DID about it
    provenance_id        TEXT NOT NULL,
    raw_hash             TEXT NOT NULL,
    supersedes_quote_id  TEXT,
    CHECK (disposition IN ('ACCEPTED','WINSORISED','EXCLUDED','QUARANTINED')),
    CHECK (cabin IN ('economy','other_than_economy')),
    CHECK (currency = 'INR')
);

-- Uniqueness on (kappa, period, source) is the idempotency guarantee: a re-run
-- cannot double-count.
CREATE UNIQUE INDEX IF NOT EXISTS ux_quote_kappa ON fact_fare_quote(
    route, carrier, apw_days, flight_number, fare_family, cabin, stops,
    collected_date, source);
CREATE INDEX IF NOT EXISTS ix_quote_cell ON fact_fare_quote(route, apw_days, collected_at_utc);
CREATE INDEX IF NOT EXISTS ix_quote_date ON fact_fare_quote(collected_date);
CREATE INDEX IF NOT EXISTS ix_quote_dep  ON fact_fare_quote(departure_date);

-- Immutability enforced by the database, not by good intentions. In Postgres
-- this is a REVOKE UPDATE grant; in SQLite a trigger is the equivalent.
CREATE TRIGGER IF NOT EXISTS trg_quote_immutable
BEFORE UPDATE ON fact_fare_quote
BEGIN
    SELECT RAISE(ABORT, 'fact_fare_quote is immutable: write a correcting row with supersedes_quote_id');
END;

CREATE TRIGGER IF NOT EXISTS trg_quote_nodelete
BEFORE DELETE ON fact_fare_quote
BEGIN
    SELECT RAISE(ABORT, 'fact_fare_quote is append-only: quotes are never deleted');
END;

CREATE TABLE IF NOT EXISTS fact_index_value (
    index_id        TEXT PRIMARY KEY,
    index_code      TEXT NOT NULL,             -- APIx-B | APIx-T | APIx-A, optionally :route:tau
    period          TEXT NOT NULL,
    frequency       TEXT NOT NULL,             -- daily | weekly | monthly
    basis           TEXT NOT NULL,             -- book | travel
    omega_preset    TEXT NOT NULL,
    value           REAL NOT NULL,
    se              REAL,
    ci_low          REAL,
    ci_high         REAL,
    n_quotes        INTEGER,
    n_cells         INTEGER,
    coverage_pct    REAL,
    omega_covered   REAL,                     -- share of omega represented
    is_synthetic    INTEGER NOT NULL DEFAULT 0,
    method_version  TEXT NOT NULL,
    weights_version TEXT NOT NULL,
    run_id          TEXT NOT NULL,
    computed_at_utc TEXT NOT NULL,
    CHECK (frequency IN ('daily','weekly','monthly')),
    CHECK (basis IN ('book','travel'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_index_value ON fact_index_value(
    index_code, period, frequency, basis, omega_preset, method_version, weights_version);
CREATE INDEX IF NOT EXISTS ix_index_lookup ON fact_index_value(index_code, frequency, basis, period);

-- --------------------------------------------------------------- governance

-- Append-only, hash-chained: h_n = SHA256(h_{n-1} || canonical(record_n)).
-- This is the artefact that makes the system deployable by a ministry.
CREATE TABLE IF NOT EXISTS ledger_provenance (
    provenance_id           TEXT PRIMARY KEY,
    seq                     INTEGER NOT NULL,
    run_id                  TEXT NOT NULL,
    source                  TEXT NOT NULL,
    ladder_rung             INTEGER NOT NULL,
    legal_basis             TEXT NOT NULL,
    request_url_hash        TEXT,
    robots_directive_applied TEXT NOT NULL,     -- ALLOWED | DISALLOWED | NOT_APPLICABLE
    rate_limit_bucket       TEXT,
    http_status             INTEGER,
    outcome                 TEXT NOT NULL,      -- OK | ROBOTS_BLOCKED | HARD_BLOCK | CIRCUIT_OPEN | ERROR | KILL_SWITCH
    n_quotes                INTEGER NOT NULL DEFAULT 0,
    fetched_at              TEXT NOT NULL,
    note                    TEXT,
    prev_hash               TEXT NOT NULL,
    this_hash               TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_ledger_seq ON ledger_provenance(seq);

CREATE TRIGGER IF NOT EXISTS trg_ledger_immutable
BEFORE UPDATE ON ledger_provenance
BEGIN
    SELECT RAISE(ABORT, 'ledger_provenance is append-only and hash-chained');
END;

CREATE TRIGGER IF NOT EXISTS trg_ledger_nodelete
BEFORE DELETE ON ledger_provenance
BEGIN
    SELECT RAISE(ABORT, 'ledger_provenance is append-only and hash-chained');
END;

-- Structured audit of every change to weights, basket or method version.
CREATE TABLE IF NOT EXISTS audit_config_change (
    id           INTEGER PRIMARY KEY,
    changed_at   TEXT NOT NULL,
    operator     TEXT NOT NULL,
    artefact     TEXT NOT NULL,                -- weights | basket | method
    from_version TEXT,
    to_version   TEXT NOT NULL,
    note         TEXT
);

-- Data-quality contract results. Publication is blocked on a BLOCK failure.
CREATE TABLE IF NOT EXISTS quality_check_result (
    id          INTEGER PRIMARY KEY,
    run_id      TEXT NOT NULL,
    checked_at  TEXT NOT NULL,
    check_class TEXT NOT NULL,
    check_name  TEXT NOT NULL,
    severity    TEXT NOT NULL,                 -- BLOCK | ALERT | QUARANTINE
    passed      INTEGER NOT NULL,
    observed    TEXT,
    detail      TEXT
);
CREATE INDEX IF NOT EXISTS ix_quality_run ON quality_check_result(run_id);

-- Cross-source measurement error: when two sources quote the same flight, the
-- difference estimates the error in our own instrument. Publishing that series
-- is the kind of thing a statistical office cares about.
-- Cross-source measurement error. Populated only when TWO OR MORE sources are
-- live: the spread between independent quotes for the same flight IS the
-- estimate of error in our own instrument. With a single source live it stays
-- empty by design, and /v1/coverage reports that rather than implying coverage.
CREATE TABLE IF NOT EXISTS fact_cross_source_spread (
    id             INTEGER PRIMARY KEY,
    collected_date TEXT NOT NULL,
    route          TEXT NOT NULL,
    carrier        TEXT NOT NULL,
    flight_number  TEXT NOT NULL,
    apw_days       INTEGER NOT NULL,
    n_sources      INTEGER NOT NULL,
    spread_pct     REAL NOT NULL,
    run_id         TEXT NOT NULL
);

-- Cell-level index detail for the headline configuration. Persisted so the
-- availability demo -- the matched / LAF / adjusted three-line chart with the
-- collapsing A area beneath it -- renders instantly instead of re-running the
-- engine per request. This is the chart that shows the surge problem seen and
-- fixed, and it has to be fast on stage.
CREATE TABLE IF NOT EXISTS fact_cell_index (
    run_id       TEXT NOT NULL,
    index_code   TEXT NOT NULL,
    basis        TEXT NOT NULL,
    period       TEXT NOT NULL,
    route        TEXT NOT NULL,
    carrier      TEXT NOT NULL,
    apw_days     INTEGER NOT NULL,
    -- matched, laf and adjusted are all PRE-SMOOTHING, so the three are
    -- directly comparable and the defining property is visible on the chart:
    -- at availability = 1 the adjusted value equals the matched value exactly.
    -- adjusted_smoothed is the same series after the 7-day centred geometric
    -- filter, which is what feeds the published index.
    matched           REAL,
    laf               REAL,
    adjusted          REAL,
    adjusted_smoothed REAL,
    availability      REAL,
    n_matched    INTEGER,
    n_quotes     INTEGER,
    suppressed   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (index_code, basis, period, route, carrier, apw_days)
);
CREATE INDEX IF NOT EXISTS ix_cell_route ON fact_cell_index(route, basis, period);

-- Official reference series: CPI (MoSPI), and later DGCA average fares and PPAC
-- ATF prices. These are the BACK-TEST COMPARATORS and the nowcast target. They
-- are loaded from published files, never scraped, and each row carries the
-- source file it came from so a comparison can be traced to its release.
CREATE TABLE IF NOT EXISTS fact_cpi_reference (
    id           INTEGER PRIMARY KEY,
    base_year    INTEGER NOT NULL,      -- 2010 | 2012 | 2024
    period       TEXT NOT NULL,         -- 'YYYY-MM-01', calendar month start
    year         INTEGER NOT NULL,
    month        INTEGER NOT NULL,
    state        TEXT NOT NULL,         -- 'All India' or a State/UT
    sector       TEXT NOT NULL,         -- Rural | Urban | Combined
    level        TEXT NOT NULL,         -- division | group | subgroup | item
    label        TEXT NOT NULL,         -- 'Transport', 'Transport and Communication', ...
    code         TEXT,
    idx          REAL,                  -- the published index value
    inflation    REAL,                  -- published y-o-y %, where given
    source_file  TEXT NOT NULL,
    loaded_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_cpi_ref ON fact_cpi_reference(
    base_year, period, state, sector, level, label);
CREATE INDEX IF NOT EXISTS ix_cpi_lookup ON fact_cpi_reference(base_year, label, sector, state, period);

-- Back-test agreement statistics: APIx vs an official comparator.
CREATE TABLE IF NOT EXISTS fact_backtest_result (
    id             INTEGER PRIMARY KEY,
    run_id         TEXT NOT NULL,
    computed_at    TEXT NOT NULL,
    apix_code      TEXT NOT NULL,
    apix_basis     TEXT NOT NULL,
    comparator     TEXT NOT NULL,
    frequency      TEXT NOT NULL,
    n_periods      INTEGER NOT NULL,
    statistic      TEXT NOT NULL,
    value          REAL,
    detail         TEXT,
    is_synthetic   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_backtest_run ON fact_backtest_result(run_id, statistic);
