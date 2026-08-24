"""Tests for cleaning, decomposition, the politeness governor and the ledger.

The governance tests are the ones that matter for deployability: they assert
that the system cannot be configured into a circumvention posture and that the
audit trail is genuinely tamper-evident.
"""
from __future__ import annotations

import sqlite3
from datetime import date

import numpy as np
import pandas as pd
import pytest

from apix_collect.politeness import CircuitBreaker, PolitenessGovernor, TokenBucket
from apix_collect.provenance import ProvenanceLedger, chain_hash, verify_chain
from apix_pipeline.clean import clean, hard_validity_gates
from apix_pipeline.decompose import ChargeBook, decompose
from apix_pipeline.quality import blocking_failures, run_contract
from apix_store import db


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_schema(c)
    db.seed_dimensions(c, db.load_config())
    yield c
    c.close()


def _quotes(n=40, route="DEL-BOM", price=5000.0, day="2026-05-01"):
    rows = []
    for i in range(n):
        rows.append(dict(collected_date=day, departure_date="2026-05-08", route=route,
                         carrier="6E", apw_days=7, flight_number=f"6E-{i//4}",
                         fare_family=["SAVER", "MID", "TOP", "FLEX"][i % 4],
                         cabin="economy", stops=0, currency="INR",
                         total_fare=price * (1 + 0.02 * (i % 5)),
                         origin_iata="DEL", dest_iata="BOM", is_sold_out=0))
    return pd.DataFrame(rows)


# ------------------------------------------------------------ decomposition

def test_decomposition_reconciles_to_within_one_rupee(conn):
    book = ChargeBook(conn, convenience_fee=299.0, rcs_levy=50.0)
    out = decompose(_quotes(), book, charge_on="2026-05-01")
    assert out["decomp_residual"].max() < 1.0


def test_gst_is_ad_valorem_on_the_fare_base(conn):
    book = ChargeBook(conn, convenience_fee=299.0)
    out = decompose(_quotes(n=4), book, charge_on="2026-05-01")
    gst_rate = book.gst_rate("economy", "2026-05-01")
    assert (out["gst"] / out["base_fare"]).round(6).eq(round(gst_rate, 6)).all()


def test_variants_are_ordered_B_le_T_le_A(conn):
    book = ChargeBook(conn, convenience_fee=299.0)
    out = decompose(_quotes(), book, charge_on="2026-05-01")
    assert (out["price_B"] <= out["price_T"] + 1e-9).all()
    assert (out["price_T"] <= out["price_A"] + 1e-9).all()


def test_convenience_fee_is_excluded_from_the_headline(conn):
    """The OTA fee is a distribution cost, not a fare. T must exclude it."""
    book = ChargeBook(conn, convenience_fee=299.0)
    out = decompose(_quotes(n=4), book, charge_on="2026-05-01")
    assert (out["price_A"] - out["price_T"]).round(6).eq(299.0).all()


def test_administered_charges_are_effective_dated(conn):
    """An index computed for an old date must use that date's UDF."""
    conn.execute("UPDATE scd_airport_charges SET effective_to = '2026-04-01' "
                 "WHERE airport_iata = 'DEL'")
    conn.execute("INSERT INTO scd_airport_charges "
                 "(airport_iata, udf_domestic, asf, effective_from, effective_to) "
                 "VALUES ('DEL', 500.0, 236.0, '2026-04-01', NULL)")
    conn.commit()
    book = ChargeBook(conn)
    assert book.udf("DEL", "2026-03-01") == 129.0
    assert book.udf("DEL", "2026-05-01") == 500.0


# ---------------------------------------------------------------- cleaning

def test_hard_gates_exclude_impossible_quotes(conn):
    q = _quotes(n=8)
    q.loc[0, "total_fare"] = -5.0
    q.loc[1, "currency"] = "USD"
    q.loc[2, "apw_days"] = 3          # not in the window set
    out = hard_validity_gates(q, distances={"DEL-BOM": 1137.0})
    assert out.loc[0, "gate_reason"] == "NONPOSITIVE_FARE"
    assert out.loc[1, "gate_reason"] == "NON_INR_CURRENCY"
    assert out.loc[2, "gate_reason"] == "APW_NOT_IN_WINDOW_SET"
    assert not out.loc[3, "gate_failed"]


def test_outliers_are_winsorised_not_deleted(conn):
    """Disposition, not deletion. The extreme keeps its direction."""
    book = ChargeBook(conn, convenience_fee=299.0)
    q = _quotes(n=40)
    q.loc[0, "total_fare"] = 45000.0        # extreme but a real fare
    dec = decompose(q, book, charge_on="2026-05-01")
    out = clean(dec, distances={"DEL-BOM": 1137.0})
    row = out.loc[0]
    assert row["disposition"] == "WINSORISED"
    assert row["quality_flag"] == "OUTLIER_CELL"
    # capped at the fence, so still above the cell median, but not at 45000
    assert row["price_T"] < 45000.0
    assert len(out) == len(q), "cleaning must never drop rows"


def test_flag_and_disposition_are_separate_columns(conn):
    book = ChargeBook(conn, convenience_fee=299.0)
    q = _quotes(n=40)
    q.loc[0, "total_fare"] = 45000.0
    out = clean(decompose(q, book, charge_on="2026-05-01"), distances={"DEL-BOM": 1137.0})
    assert "quality_flag" in out.columns and "disposition" in out.columns
    assert out.loc[0, "quality_flag"] != out.loc[0, "disposition"]


def test_sold_out_is_quarantined_not_excluded(conn):
    """Sold out is a price signal, not bad data. It must stay auditable."""
    book = ChargeBook(conn, convenience_fee=299.0)
    q = _quotes(n=8)
    q.loc[0, "is_sold_out"] = 1
    q.loc[0, "total_fare"] = None
    out = clean(decompose(q, book, charge_on="2026-05-01"), distances={"DEL-BOM": 1137.0})
    assert out.loc[0, "disposition"] == "QUARANTINED"
    assert out.loc[0, "quality_flag"] == "SOLD_OUT"


def test_tukey_multiplier_is_three_not_one_point_five(conn):
    """1.5 would trim genuinely dispersed fares. Assert the looser fence holds."""
    book = ChargeBook(conn, convenience_fee=299.0)
    q = _quotes(n=40)
    q["total_fare"] = np.linspace(3000, 12000, 40)     # wide but legitimate
    out = clean(decompose(q, book, charge_on="2026-05-01"), distances={"DEL-BOM": 1137.0})
    assert (out["disposition"] == "ACCEPTED").all()


# ------------------------------------------------------- provenance ledger

def test_ledger_chain_verifies(conn):
    led = ProvenanceLedger(conn, "run-1")
    for i in range(5):
        led.record(source="synthetic_replay", ladder_rung=0, legal_basis="simulator",
                   outcome="OK", n_quotes=10 * i)
    result = verify_chain(conn)
    assert result["n_records"] == 5
    assert result["intact"] is True
    assert result["first_broken_seq"] is None


def test_ledger_detects_tampering(conn):
    """Tamper-evidence, demonstrated rather than claimed."""
    led = ProvenanceLedger(conn, "run-1")
    for i in range(5):
        led.record(source="synthetic_replay", ladder_rung=0, legal_basis="simulator",
                   outcome="OK", n_quotes=i)
    assert verify_chain(conn)["intact"] is True

    # The triggers block UPDATE, so a tamperer has to go around them. Even then
    # the chain catches it.
    conn.execute("DROP TRIGGER trg_ledger_immutable")
    conn.execute("UPDATE ledger_provenance SET n_quotes = 9999 WHERE seq = 3")
    conn.commit()

    result = verify_chain(conn)
    assert result["intact"] is False
    assert result["first_broken_seq"] == 3


def test_ledger_rejects_updates_and_deletes(conn):
    led = ProvenanceLedger(conn, "run-1")
    led.record(source="s", ladder_rung=0, legal_basis="b", outcome="OK")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE ledger_provenance SET outcome = 'X'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM ledger_provenance")


def test_quotes_are_immutable(conn):
    """A mutable price table is disqualifying for official statistics."""
    led = ProvenanceLedger(conn, "r")
    pid = led.record(source="synthetic_replay", ladder_rung=0, legal_basis="sim", outcome="OK")
    db.insert_quotes(conn, [dict(
        quote_id="q1", run_id="r", collected_at_utc="2026-05-01T00:00:00Z",
        collected_at_ist="2026-05-01T05:30:00+05:30", collected_date="2026-05-01",
        route="DEL-BOM", carrier="6E", source="synthetic_replay", flight_number="6E-1",
        departure_date="2026-05-08", apw_days=7, cabin="economy", fare_family="SAVER",
        stops=0, currency="INR", total_fare=5000.0, is_sold_out=0, is_synthetic=1,
        disposition="ACCEPTED", provenance_id=pid, raw_hash="abc")])
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE fact_fare_quote SET total_fare = 1.0 WHERE quote_id = 'q1'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM fact_fare_quote WHERE quote_id = 'q1'")


def test_robots_blocked_requests_are_recorded_not_silently_skipped(conn):
    """We must be able to prove what we did NOT do."""
    led = ProvenanceLedger(conn, "run-1")
    led.record(source="permitted_public_page", ladder_rung=3, legal_basis="implied licence",
               outcome="ROBOTS_BLOCKED", robots_directive="DISALLOWED",
               note="robots.txt disallows the path")
    row = conn.execute("SELECT outcome, robots_directive_applied FROM ledger_provenance").fetchone()
    assert row["outcome"] == "ROBOTS_BLOCKED"
    assert row["robots_directive_applied"] == "DISALLOWED"


# ---------------------------------------------------- the politeness governor

ROBOTS_DISALLOW = "User-agent: *\nDisallow: /flights\nCrawl-delay: 30\n"
ROBOTS_ALLOW = "User-agent: *\nAllow: /\nCrawl-delay: 20\n"


def _gov(robots_text, **over):
    cfg = {"user_agent": "APIx-Research/1.0", "respect_robots": True,
           "default_crawl_delay_s": 10.0, "max_concurrency_per_host": 1,
           "circuit_breaker_threshold": 3, "hard_block_statuses": [403, 429]}
    cfg.update(over)
    return PolitenessGovernor(cfg, robots_fetcher=lambda url: robots_text)


def test_governor_never_issues_a_disallowed_request():
    d = _gov(ROBOTS_DISALLOW).check("https://example.com/flights/search?x=1")
    assert d.allowed is False
    assert d.outcome == "ROBOTS_BLOCKED"
    assert d.robots_directive == "DISALLOWED"


def test_governor_allows_a_permitted_path():
    d = _gov(ROBOTS_ALLOW).check("https://example.com/public/fares")
    assert d.allowed is True
    assert d.robots_directive == "ALLOWED"


def test_unreadable_robots_fails_closed():
    """Failing closed is the only defensible default for a government product."""
    def boom(url):
        raise OSError("network down")
    g = PolitenessGovernor({"respect_robots": True, "user_agent": "APIx-Research/1.0"},
                           robots_fetcher=boom)
    d = g.check("https://example.com/anything")
    assert d.allowed is False
    assert d.outcome == "ROBOTS_BLOCKED"


def test_kill_switch_disables_a_host_instantly():
    g = _gov(ROBOTS_ALLOW, kill_switch_hosts=["example.com"])
    d = g.check("https://example.com/public/fares")
    assert d.allowed is False and d.outcome == "KILL_SWITCH"


def test_circuit_breaker_opens_after_three_hard_blocks():
    g = _gov(ROBOTS_ALLOW)
    url = "https://example.com/public/fares"
    assert g.on_response(url, 429) == "HARD_BLOCK"
    assert g.on_response(url, 429) == "HARD_BLOCK"
    assert g.on_response(url, 429) == "CIRCUIT_OPEN"
    assert g.check(url).outcome == "CIRCUIT_OPEN"


def test_hard_block_never_retries():
    """403/429 must stop the host, not trigger a backoff-and-retry loop."""
    for status in (401, 403, 429):
        gg = _gov(ROBOTS_ALLOW, hard_block_statuses=[401, 403, 429])
        assert gg.on_response("https://h.com/x", status) in ("HARD_BLOCK", "CIRCUIT_OPEN")


def test_concurrency_ceiling_is_one():
    """One in-flight request per host. Not 8, not 4."""
    assert _gov(ROBOTS_ALLOW).max_concurrency == 1


def test_token_bucket_enforces_the_declared_crawl_delay():
    b = TokenBucket(rate_per_s=1.0 / 30.0)
    assert b.take(now=0.0) == 0.0             # first request goes through
    wait = b.take(now=0.0)                    # second immediately after must wait
    assert wait == pytest.approx(30.0, rel=0.01)


def test_circuit_breaker_reopens_after_cooldown():
    cb = CircuitBreaker(threshold=2, cooldown_s=100.0)
    cb.record_block(now=0.0)
    cb.record_block(now=0.0)
    assert cb.is_open(now=50.0) is True
    assert cb.is_open(now=150.0) is False


def test_no_circumvention_code_exists_anywhere_in_the_package():
    """A structural assertion: the capability is absent, not merely unused.

    If someone adds a CAPTCHA solver or a proxy rotator, this test fails.
    """
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1] / "src"
    banned = ["2captcha", "anticaptcha", "capmonster", "deathbycaptcha",
              "solve_captcha", "captcha_solver", "rotate_proxy", "proxy_pool",
              "residential_proxy", "undetected_chromedriver", "selenium_stealth"]
    hits = []
    for path in src.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for token in banned:
            # The word "captcha" appears in policy prose; the BANNED tokens are
            # library and function names, which prose does not contain.
            if token in text:
                hits.append(f"{path.name}: {token}")
    assert not hits, f"circumvention tooling found: {hits}"


# -------------------------------------------------------- quality contract

def test_quality_contract_blocks_on_arithmetic_failure(conn):
    book = ChargeBook(conn, convenience_fee=299.0)
    q = decompose(_quotes(), book, charge_on="2026-05-01")
    q = clean(q, distances={"DEL-BOM": 1137.0})
    q["base_fare"] = q["base_fare"] * 1.5          # break the reconciliation
    results = run_contract(q)
    names = [b["check_name"] for b in blocking_failures(results)]
    assert "components_resum_to_total" in names


def test_quality_contract_passes_on_clean_data(conn):
    book = ChargeBook(conn, convenience_fee=299.0)
    q = clean(decompose(_quotes(), book, charge_on="2026-05-01"),
              distances={"DEL-BOM": 1137.0})
    q["source"] = "synthetic_replay"
    assert blocking_failures(run_contract(q)) == []


def test_quality_contract_blocks_on_duplicate_kappa(conn):
    book = ChargeBook(conn, convenience_fee=299.0)
    q = clean(decompose(_quotes(), book, charge_on="2026-05-01"),
              distances={"DEL-BOM": 1137.0})
    q["source"] = "synthetic_replay"
    dupe = pd.concat([q, q.iloc[[0]]], ignore_index=True)
    names = [b["check_name"] for b in blocking_failures(run_contract(dupe))]
    assert "no_duplicate_kappa_t_source" in names


# ------------------------------------------------------------------ weights

def test_carrier_weights_reproduce_published_market_shares(conn):
    """phi must track DGCA passenger shares, not square them."""
    cfg = db.load_config()
    w = db.build_weights(conn, cfg)
    phi = w.carrier_weights["DEL-BOM"]
    share = {c["iata"]: c["national_share"] for c in cfg["carriers"]["carriers"]}
    assert sum(phi.values()) == pytest.approx(1.0)
    for iata, published in share.items():
        assert abs(phi[iata] - published) < 0.03, f"{iata} weight strays from its share"


def test_psd_supplied_weights_override_derived_ones(conn, tmp_path, monkeypatch):
    """PSD, not the team, owns the weights."""
    import yaml
    from apix_store import db as dbmod
    cfg = db.load_config()                      # load BEFORE redirecting CONFIG_DIR
    override = tmp_path / "psd_weights.yaml"
    override.write_text(yaml.safe_dump({
        "weights_version": "psd-2026-signed",
        "route_weights": {"DEL-BOM": 1.0},
        "carrier_weights": {"DEL-BOM": {"6E": 1.0}}}), encoding="utf-8")
    monkeypatch.setattr(dbmod, "CONFIG_DIR", tmp_path)
    w = dbmod.build_weights(conn, cfg)
    assert w.weights_version == "psd-2026-signed"
    assert w.route_weights == {"DEL-BOM": 1.0}
    assert "PSD-supplied" in w.source


# --------------------------------------- winsorisation survives persistence

def test_winsorised_cap_survives_the_store_round_trip(conn):
    """Regression: a quote labelled WINSORISED must not enter the index uncapped.

    `clean()` capped only the in-memory price column, while the store kept
    `total_fare` and `attach_variant_prices()` recomputed prices from it. The
    cap was therefore discarded and the quote entered the index at its full
    extreme value -- the disposition asserting a treatment that had not been
    applied to the number. On a 45,000 outlier in a ~5,000 cell that is the
    difference between a correct index and a badly wrong one.
    """
    from apix_pipeline import run_index

    book = ChargeBook(conn, convenience_fee=299.0, rcs_levy=50.0)
    q = _quotes(n=40)
    q.loc[0, "total_fare"] = 45000.0
    cleaned = clean(decompose(q, book, charge_on="2026-05-01"),
                    distances={"DEL-BOM": 1137.0})
    assert cleaned.loc[0, "disposition"] == "WINSORISED"

    capped_price = float(cleaned.loc[0, "price_T"])
    assert capped_price < 20000.0, "the cap itself must bind"
    assert float(cleaned.loc[0, "total_fare"]) == 45000.0, "observation stays immutable"
    assert pd.notna(cleaned.loc[0, "total_fare_capped"])

    # Re-derive exactly as the index run does after reading the store back.
    back = run_index.attach_variant_prices(cleaned)
    assert float(back.loc[0, "price_T"]) == pytest.approx(capped_price, abs=0.01)
    assert float(back.loc[0, "price_A"]) == pytest.approx(
        float(cleaned.loc[0, "total_fare_capped"]), abs=0.01)
    assert float(back.loc[0, "price_B"]) < capped_price


def test_non_winsorised_rows_are_untouched_by_the_cap_path(conn):
    from apix_pipeline import run_index
    book = ChargeBook(conn, convenience_fee=299.0, rcs_levy=50.0)
    q = _quotes(n=40)
    q.loc[0, "total_fare"] = 45000.0
    cleaned = clean(decompose(q, book, charge_on="2026-05-01"),
                    distances={"DEL-BOM": 1137.0})
    back = run_index.attach_variant_prices(cleaned)
    untouched = [i for i in cleaned.index if cleaned.loc[i, "disposition"] == "ACCEPTED"]
    assert untouched
    for i in untouched:
        assert float(back.loc[i, "price_T"]) == pytest.approx(
            float(cleaned.loc[i, "price_T"]), abs=1e-9)
        assert pd.isna(cleaned.loc[i, "total_fare_capped"])


def test_attach_variant_prices_works_without_the_capped_column(conn):
    """Backwards compatibility with a store written before the column existed."""
    from apix_pipeline import run_index
    df = pd.DataFrame([{"total_fare": 5000.0, "base_fare": 4200.0, "yq_yr": 0.0,
                        "udf": 129.0, "asf": 236.0, "rcs_levy": 0.0, "gst": 210.0,
                        "convenience_fee": 299.0}])
    out = run_index.attach_variant_prices(df)
    assert float(out.loc[0, "price_A"]) == 5000.0
    assert float(out.loc[0, "price_T"]) == pytest.approx(4701.0)


def test_migration_adds_the_capped_column_to_an_existing_store(tmp_path):
    """CREATE TABLE IF NOT EXISTS does nothing to an existing table."""
    import sqlite3 as sq
    path = tmp_path / "old.db"
    c = db.connect(path)
    db.init_schema(c)
    c.execute("ALTER TABLE fact_fare_quote DROP COLUMN total_fare_capped")
    c.commit()
    cols = {r["name"] for r in c.execute("PRAGMA table_info(fact_fare_quote)")}
    assert "total_fare_capped" not in cols
    db.init_schema(c)                      # re-running init must migrate
    cols = {r["name"] for r in c.execute("PRAGMA table_info(fact_fare_quote)")}
    assert "total_fare_capped" in cols
    c.close()
