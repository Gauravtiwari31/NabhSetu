"""Tests for the CPI loader, the back-test harness and the nowcast bridge.

The load-bearing tests here are the REFUSAL tests. A back-test that always
produces numbers and a bridge that always produces coefficients are worse than
useless on a short or synthetic sample -- they manufacture confidence. These
tests assert that both modules decline to report when they should.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apix_pipeline import backtest, nowcast
from apix_reference import cpi
from apix_store import db


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "ref.db")
    db.init_schema(c)
    yield c
    c.close()


def _cpi_frame(n=40, start="2023-01-01", drift=0.002, seed=0):
    rng = np.random.default_rng(seed)
    periods = pd.date_range(start, periods=n, freq="MS")
    idx = 100 * np.exp(np.cumsum(rng.normal(drift, 0.004, n)))
    return pd.DataFrame({"period": periods.strftime("%Y-%m-%d"), "idx": idx,
                         "inflation": np.nan})


def _apix_from(cpi_df, beta=0.6, noise=0.004, seed=1):
    rng = np.random.default_rng(seed)
    base = cpi_df["idx"].to_numpy(float)
    val = 100 * np.exp(beta * np.log(base / base[0]) + rng.normal(0, noise, base.size))
    return pd.DataFrame({"period": cpi_df["period"], "value": val})


# ------------------------------------------------------------- CPI loader

def test_month_names_and_numbers_both_parse():
    assert cpi._month_number("January") == 1
    assert cpi._month_number("july") == 7
    assert cpi._month_number("Sep") == 9
    assert cpi._month_number(12) == 12
    assert cpi._month_number("nonsense") is None
    assert cpi._month_number(np.nan) is None


def test_tidy_takes_the_deepest_populated_level():
    """A release carrying item detail must not be flattened to division."""
    df = pd.DataFrame({
        "year": [2026, 2026], "month": ["July", "July"],
        "state": ["All India", "All India"], "sector": ["Combined", "Combined"],
        "division": ["Transport", "Transport"],
        "group": [None, "Transport services"],
        "item": [None, "Passenger transport by air"],
        "index": [105.6, 112.3], "inflation": [4.4, 9.1], "code": ["7", "7.3.3"],
    })
    out = cpi._tidy(df, 2024, "test.xlsx")
    assert list(out["level"]) == ["division", "item"]
    assert out.loc[out.level == "item", "label"].iloc[0] == "Passenger transport by air"
    assert list(out["period"]) == ["2026-07-01", "2026-07-01"]


def test_tidy_rejects_a_frame_with_no_classification():
    df = pd.DataFrame({"year": [2026], "month": ["July"], "state": ["All India"],
                       "sector": ["Combined"], "index": [100.0], "division": [None]})
    with pytest.raises(ValueError, match="no populated classification level"):
        cpi._tidy(df, 2024, "empty.xlsx")


def test_find_air_fare_item_reports_absence_rather_than_substituting(conn):
    """The whole point: if there is no air item, say so. Do not fall back."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO fact_cpi_reference (base_year, period, year, month, state, sector, "
        "level, label, code, idx, inflation, source_file, loaded_at) "
        "VALUES (2024,'2026-07-01',2026,7,'All India','Combined','division','Transport',"
        "'7',105.6,4.4,'t.xlsx',?)", [now])
    conn.commit()
    assert len(cpi.find_air_fare_item(conn)) == 0
    assert len(cpi.transport_series(conn, 2024)) == 1


# ------------------------------------------------------------- back-test

def test_backtest_refuses_below_the_minimum_overlap(conn):
    c = _cpi_frame(n=3)
    a = _apix_from(c)
    res = backtest.run(conn, a, c, persist=False)
    assert res["reportable"] is False
    assert res["statistics"] == {}
    assert any("at least 6" in x for x in res["caveats"])


def test_backtest_refuses_when_there_is_no_overlap_at_all(conn):
    c = _cpi_frame(n=12, start="2025-01-01")
    a = _apix_from(_cpi_frame(n=12, start="2030-01-01"))
    res = backtest.run(conn, a, c, persist=False)
    assert res["n_overlapping_months"] == 0
    assert res["reportable"] is False


def test_backtest_flags_a_non_item_comparator(conn):
    c = _cpi_frame(n=24)
    res = backtest.run(conn, _apix_from(c), c, comparator_level="division", persist=False)
    assert any("not the air fare item" in x for x in res["caveats"])


def test_backtest_flags_synthetic_input_as_non_validating(conn):
    c = _cpi_frame(n=24)
    res = backtest.run(conn, _apix_from(c), c, is_synthetic=True, persist=False)
    assert any("SYNTHETIC" in x for x in res["caveats"])


def test_backtest_recovers_a_known_relationship(conn):
    """Built-in correlation must be detected, or the harness is not measuring."""
    c = _cpi_frame(n=36)
    a = _apix_from(c, beta=0.8, noise=0.002)
    res = backtest.run(conn, a, c, persist=False)
    assert res["reportable"] is True
    assert res["statistics"]["pearson_r_level"] > 0.9
    assert res["statistics"]["directional_agreement_pct"] > 60


def test_backtest_reports_no_relationship_when_there_is_none(conn):
    """The unflattering case must come out unflattering."""
    rng = np.random.default_rng(7)
    c = _cpi_frame(n=48, seed=3)
    a = pd.DataFrame({"period": c["period"],
                      "value": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(c))))})
    res = backtest.run(conn, a, c, persist=False)
    assert res["reportable"] is True
    assert abs(res["statistics"]["pearson_r_mom_change"]) < 0.5


def test_bland_altman_identity():
    x = np.array([100.0, 101.0, 102.0])
    out = backtest.bland_altman(x, x)
    assert out["bias"] == pytest.approx(0.0)
    assert out["mean_abs_diff"] == pytest.approx(0.0)


def test_directional_agreement_perfect_and_opposite():
    up = np.array([1.0, 2.0, 3.0, 4.0])
    assert backtest.directional_agreement(up, up)["directional_agreement_pct"] == 100.0
    assert backtest.directional_agreement(up, up[::-1])["directional_agreement_pct"] == 0.0


def test_backtest_persists_results(conn):
    c = _cpi_frame(n=30)
    backtest.run(conn, _apix_from(c), c, run_id="bt-test", persist=True)
    n = db.table_count(conn, "fact_backtest_result")
    assert n > 0
    row = conn.execute("SELECT statistic, value FROM fact_backtest_result "
                       "WHERE run_id='bt-test' LIMIT 1").fetchone()
    assert row["statistic"]


# --------------------------------------------------------------- nowcast

def test_nowcast_refuses_on_too_few_observations():
    c = _cpi_frame(n=20)                    # y-o-y costs 12 -> ~7 usable
    design = nowcast.build_design(_apix_from(c), c)
    fit = nowcast.fit(design)
    assert fit.interpretable is False
    assert any("usable observations" in r or "per parameter" in r for r in fit.reasons)


def test_nowcast_refuses_on_synthetic_input_even_with_plenty_of_data():
    c = _cpi_frame(n=90)
    design = nowcast.build_design(_apix_from(c), c)
    fit = nowcast.fit(design, is_synthetic=True)
    assert fit.interpretable is False
    assert any("SYNTHETIC" in r for r in fit.reasons)


def test_nowcast_is_interpretable_on_a_long_real_looking_sample():
    c = _cpi_frame(n=120)
    design = nowcast.build_design(_apix_from(c), c)
    fit = nowcast.fit(design, is_synthetic=False)
    assert fit.interpretable is True
    assert fit.reasons == []
    assert fit.n_obs >= nowcast.MIN_OBS_ABSOLUTE
    assert "const" in fit.coefficients


def test_nowcast_handles_an_empty_overlap_without_crashing():
    c = _cpi_frame(n=30, start="2025-01-01")
    a = _apix_from(_cpi_frame(n=30, start="2035-01-01"))
    fit = nowcast.fit(nowcast.build_design(a, c))
    assert fit.interpretable is False
    assert fit.n_obs == 0


def test_target_is_yoy_log_inflation():
    c = _cpi_frame(n=30)
    design = nowcast.build_design(_apix_from(c), c)
    # First 12 months cannot have a y-o-y value.
    assert design["cpi_infl"].head(12).isna().all()
    expected = 100.0 * (np.log(c["idx"].iloc[12]) - np.log(c["idx"].iloc[0]))
    assert design["cpi_infl"].iloc[12] == pytest.approx(expected)


def test_oos_evaluation_is_expanding_window_not_random():
    """A random split leaks the future; assert we score strictly forward."""
    c = _cpi_frame(n=120)
    design = nowcast.build_design(_apix_from(c), c)
    fit = nowcast.fit(design)
    assert fit.oos["n_oos"] > 0
    assert "rmse_no_change_benchmark" in fit.oos
    assert isinstance(fit.oos["beats_benchmark"], bool)


def test_oos_declines_when_the_sample_is_too_short():
    c = _cpi_frame(n=26)
    design = nowcast.build_design(_apix_from(c), c)
    d = design[["cpi_infl", "apix_g_l0"]].dropna()
    out = nowcast.expanding_window_oos(d, ["apix_g_l0"], min_train=12, min_oos=6)
    assert out["n_oos"] == 0
    assert "note" in out


def test_granger_declines_on_a_short_sample():
    c = _cpi_frame(n=24)
    design = nowcast.build_design(_apix_from(c), c)
    out = nowcast.granger_causality(design)
    assert out["testable"] is False
    assert "power" in out["note"]


def test_granger_runs_on_a_long_sample():
    c = _cpi_frame(n=140)
    design = nowcast.build_design(_apix_from(c), c)
    out = nowcast.granger_causality(design)
    assert out["testable"] is True
    assert "f_stat" in out and np.isfinite(out["f_stat"])


# ------------------------------------------------------- JSON serialisation

def test_records_converts_nan_and_inf_to_null():
    """Regression: `df.where(df.notna(), None)` leaves NaN in float columns.

    json.dumps then raises "Out of range float values are not JSON compliant".
    It only bites on PARTIALLY-null columns, which is why it stayed hidden
    until a CPI series with some published inflation values and some blanks
    came through /v1/cpi.
    """
    import json
    from apix_api.main import _records

    df = pd.DataFrame({
        "period": ["2025-01-01", "2025-02-01", "2025-03-01"],
        "idx": [100.5, 101.0, 102.0],
        "inflation": [np.nan, 1.5, np.inf],      # partially null + infinite
    })
    recs = _records(df)
    assert recs[0]["inflation"] is None
    assert recs[1]["inflation"] == 1.5
    assert recs[2]["inflation"] is None
    json.dumps(recs)          # must not raise


def test_records_leaves_a_fully_populated_frame_intact():
    from apix_api.main import _records
    df = pd.DataFrame({"a": [1.0, 2.0], "b": ["x", "y"]})
    assert _records(df) == [{"a": 1.0, "b": "x"}, {"a": 2.0, "b": "y"}]


def test_backtest_aligned_payload_is_json_serialisable(conn):
    import json
    c = _cpi_frame(n=24)
    res = backtest.run(conn, _apix_from(c), c, persist=False)
    json.dumps(res["aligned"])
