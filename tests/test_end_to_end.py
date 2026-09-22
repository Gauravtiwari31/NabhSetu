"""End-to-end: collect -> clean -> index -> publish -> serve, on a throwaway DB.

This is the test that proves `docker compose up` / `python cli.py` works on a
cold machine, and it is also the reproducibility guarantee in executable form.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import pandas as pd
import pytest

from apix_collect import runner
from apix_collect.provenance import verify_chain
from apix_pipeline import run_index
from apix_pipeline.run_index import PublicationBlocked
from apix_store import db

ROUTES = ["DEL-BOM", "BOM-DEL", "DEL-BLR", "BLR-DEL"]
START = date(2026, 8, 1)
DAYS = 12


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Collect a short history and publish an index, once for the module."""
    path = tmp_path_factory.mktemp("e2e") / "apix.db"
    # The simulator ships disabled so it cannot run in a deployment by
    # accident. The end-to-end test is exactly the case that needs it, so it
    # opts in explicitly rather than the shipped config being loosened.
    cfg = db.load_config(enable_simulator=True)
    conn = db.connect(path)
    db.init_schema(conn)
    db.seed_dimensions(conn, cfg)
    db.seed_dim_date(conn, START - timedelta(days=5), START + timedelta(days=90))

    runner.backfill(conn, cfg, START, START + timedelta(days=DAYS - 1),
                    run_id="e2e-collect", routes=ROUTES)

    weights = db.build_weights(conn, cfg)
    out = run_index.run(conn, cfg, weights, variants=["T"], bases=["book"],
                        presets=["uniform"], run_id="e2e-index", bootstrap_draws=50)
    return conn, cfg, weights, out


def test_quotes_landed(built):
    conn, *_ = built
    n = db.table_count(conn, "fact_fare_quote")
    assert n > 0
    span = conn.execute("SELECT COUNT(DISTINCT collected_date) d, COUNT(DISTINCT route) r "
                        "FROM fact_fare_quote").fetchone()
    assert span["d"] == DAYS
    assert span["r"] == len(ROUTES)


def test_every_quote_carries_a_resolvable_legal_basis(built):
    """No quote may exist whose provenance cannot be resolved to a legal basis."""
    conn, *_ = built
    orphans = conn.execute(
        "SELECT COUNT(*) n FROM fact_fare_quote q LEFT JOIN ledger_provenance l "
        "ON q.provenance_id = l.provenance_id WHERE l.provenance_id IS NULL").fetchone()["n"]
    assert orphans == 0
    blank = conn.execute(
        "SELECT COUNT(*) n FROM ledger_provenance WHERE legal_basis IS NULL "
        "OR TRIM(legal_basis) = ''").fetchone()["n"]
    assert blank == 0


def test_hash_chain_intact_after_a_full_run(built):
    conn, *_ = built
    chain = verify_chain(conn)
    assert chain["intact"] is True
    assert chain["n_records"] > 0


def test_index_published_with_versions_stamped(built):
    conn, cfg, weights, out = built
    assert out["n_index_values"] > 0
    row = conn.execute("SELECT * FROM fact_index_value LIMIT 1").fetchone()
    assert row["method_version"] == cfg["method"]["method_version"]
    assert row["weights_version"] == weights.weights_version
    assert row["is_synthetic"] == 1, "simulator output must be stamped synthetic"


def test_base_period_sits_at_the_published_base_level(built):
    conn, cfg, *_ = built
    first = conn.execute(
        "SELECT value FROM fact_index_value WHERE index_code='APIx-T' AND frequency='daily' "
        "AND basis='book' ORDER BY period LIMIT 1").fetchone()
    # The base period is 100 on the native scale, and `link_factor` once the
    # series is chain-linked onto an earlier base (config/method.yaml `linkage`).
    # The 7-day centred filter moves the endpoint, so assert a tight
    # neighbourhood of that level rather than the level exactly.
    linkage = cfg["method"].get("linkage") or {}
    expected = float(linkage["link_factor"]) if linkage.get("enabled") else 100.0
    assert expected * 0.97 < first["value"] < expected * 1.03


def test_recomputation_is_bit_identical(built):
    """The reproducibility guarantee: same inputs, same numbers."""
    conn, cfg, weights, _ = built
    before = pd.read_sql_query(
        "SELECT index_code, period, frequency, basis, omega_preset, value "
        "FROM fact_index_value ORDER BY index_code, period, frequency", conn)
    run_index.run(conn, cfg, weights, variants=["T"], bases=["book"], presets=["uniform"],
                  run_id="e2e-index-again", bootstrap_draws=50)
    after = pd.read_sql_query(
        "SELECT index_code, period, frequency, basis, omega_preset, value "
        "FROM fact_index_value ORDER BY index_code, period, frequency", conn)
    pd.testing.assert_frame_equal(before, after)


def test_collection_is_idempotent(built):
    """Re-running a day must not double-count."""
    conn, cfg, *_ = built
    before = db.table_count(conn, "fact_fare_quote")
    runner.collect_day(conn, cfg, START, "e2e-rerun", routes=ROUTES)
    assert db.table_count(conn, "fact_fare_quote") == before


def test_quality_contract_ran_and_was_recorded(built):
    conn, *_ = built
    n = db.table_count(conn, "quality_check_result")
    assert n > 0
    blocking = conn.execute(
        "SELECT COUNT(*) n FROM quality_check_result WHERE severity='BLOCK' AND passed=0"
    ).fetchone()["n"]
    assert blocking == 0, "a BLOCK failure must never coexist with a published index"


def test_publication_is_blocked_when_the_chain_is_broken(built, tmp_path):
    """Tamper with the ledger and publication must refuse to proceed."""
    conn, cfg, weights, _ = built
    conn.execute("DROP TRIGGER IF EXISTS trg_ledger_immutable")
    conn.execute("UPDATE ledger_provenance SET n_quotes = n_quotes + 1 "
                 "WHERE seq = (SELECT MIN(seq) FROM ledger_provenance)")
    conn.commit()
    try:
        with pytest.raises(PublicationBlocked):
            run_index.run(conn, cfg, weights, variants=["T"], bases=["book"],
                          presets=["uniform"], run_id="e2e-blocked", bootstrap_draws=0)
    finally:
        conn.execute("UPDATE ledger_provenance SET n_quotes = n_quotes - 1 "
                     "WHERE seq = (SELECT MIN(seq) FROM ledger_provenance)")
        conn.commit()


def test_api_serves_the_published_index(built, monkeypatch):
    conn, *_ = built
    path = conn.execute("PRAGMA database_list").fetchone()["file"]
    monkeypatch.setenv("APIX_DB", path)

    from fastapi.testclient import TestClient
    import apix_api.main as api
    client = TestClient(api.app)

    assert client.get("/health").status_code == 200

    r = client.get("/v1/index?variant=T&frequency=daily&basis=book")
    assert r.status_code == 200
    body = r.json()
    assert body["is_synthetic"] is True
    assert "SYNTHETIC" in body, "synthetic output must be labelled in the payload"
    assert len(body["observations"]) == DAYS

    cov = client.get("/v1/coverage").json()
    assert cov["routes_collected"] == len(ROUTES)
    assert cov["coverage_by_traffic_weight_pct"] < 100.0, \
        "coverage must be reported against the full basket, not renormalised"

    meth = client.get("/v1/methodology").json()
    assert "solve, bypass or outsource a CAPTCHA" in meth["collection_policy"]["will_not"]
    assert "None collected" in meth["personal_data"]

    sdmx = client.get("/v1/index?format=sdmx-json&frequency=daily").json()
    assert "dataSets" in sdmx["data"]
    assert sdmx["data"]["structure"]["dimensions"]["series"][0]["id"] == "INDEX"

    iid = body["observations"][-1]["index_id"]
    prov = client.get(f"/v1/provenance/{iid}").json()
    assert prov["hash_chain"]["intact"] is True
    assert prov["quotes_behind_it"]["n_quotes"] > 0
    assert len(prov["ledger_segment"]) > 0


def test_availability_series_is_persisted_and_served(built, monkeypatch):
    conn, *_ = built
    monkeypatch.setenv("APIX_DB", conn.execute("PRAGMA database_list").fetchone()["file"])
    from fastapi.testclient import TestClient
    import apix_api.main as api
    r = TestClient(api.app).get("/v1/availability/series?route=DEL-BOM")
    assert r.status_code == 200
    obs = r.json()["observations"]
    assert len(obs) > 0
    assert all(k in obs[0] for k in ("matched", "laf", "adjusted", "availability"))
