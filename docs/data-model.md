# Data model

Primary store: PostgreSQL with Timescale hypertables for time-series facts.
Tests may use SQLite with the same SQLAlchemy models (no hypertables).

## Registry (mutable)

- `sources` — identity, enablement, human-reviewed robots/terms status
- `source_capabilities` — technical capabilities; discovery cannot set `automation_allowed`
- `source_policies` — interval, concurrency, daily cap, allowed routes/paths
- `source_network_policies` — egress mode and rotation strategy (never credentials)
- `source_adapter_stats` — per-modality success, latency, circuit state

## Egress

- `egress_nodes` — provider, region, **secret reference**, health
- `egress_sessions` — sticky identity until expiry or explicit restart

## Execution

- `collection_jobs` / `collection_attempts`
- `compliance_leases` / `source_rate_windows`

Attempts record `egress_id`, region, session, HTTP category, network-failure
category, and failover count.

## Immutable ledger

UPDATE/DELETE are rejected by database triggers on:

- `payload_artifacts`
- `raw_observations` (Timescale hypertable on `collected_at`)
- `normalised_observations` (Timescale hypertable on `collected_at`)
- `fare_components`
- `validation_flags`
- `provenance_records`

Corrections append a row with `supersedes_id`. Money uses `NUMERIC`, never float.

## Index publication

- `basket_versions` / `weight_versions` — versioned basket and injected weights
- `index_runs` — method, hashes, coverage, simulated flag
- `elementary_cells` — route/carrier/lead cells for a run
- `published_index_values` — daily/weekly/monthly headline, route, and APW series
- `quality_checks` — publication dispositions
- `reference_observations` — imported DGCA/CPI file rows with checksums
- `backtest_results` — honest `reportable` / `not_reportable` / `unavailable` outcomes


## Identifiers

UUIDs, UTC timestamps, IATA airport/carrier codes, ISO currency.
