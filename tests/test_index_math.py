"""Unit and property tests for the index arithmetic.

These are the tests that matter to a statistician judge: the formulae are
checked against hand-computed values and against their defining mathematical
properties, not against whatever the code happened to produce.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apix_index import (KAPPA, MethodConfig, WeightSet, aggregate_apw, availability_ratio, blend,
                        carli, centred_geometric_ma, compute, dutot, geometric_mean, jevons,
                        jevons_se, log_relatives)
from apix_index.uncertainty import delta_method_se, flight_block_bootstrap


# --------------------------------------------------------------- elementary

def test_jevons_hand_computed():
    # Two products, one doubles, one halves. The geometric mean of the
    # relatives is exactly 1, so the index is exactly 100.
    assert jevons([100.0, 100.0], [200.0, 50.0]) == pytest.approx(100.0)


def test_jevons_uniform_price_change():
    # Every price up 10% -> index exactly 110, for all three formulae.
    p0 = [1000.0, 2500.0, 7000.0]
    pt = [p * 1.10 for p in p0]
    assert jevons(p0, pt) == pytest.approx(110.0)
    assert dutot(p0, pt) == pytest.approx(110.0)
    assert carli(p0, pt) == pytest.approx(110.0)


def test_am_gm_ordering_dutot_jevons_carli():
    """Carli >= Jevons always (AM-GM on the price relatives)."""
    rng = np.random.default_rng(11)
    for _ in range(200):
        n = int(rng.integers(2, 30))
        p0 = rng.uniform(1000, 20000, size=n)
        pt = p0 * np.exp(rng.normal(0, 0.3, size=n))
        assert carli(p0, pt) >= jevons(p0, pt) - 1e-9


def test_jevons_satisfies_time_reversal():
    """I(0,t) * I(t,0) = 100^2 / 100 -- Carli does not satisfy this."""
    rng = np.random.default_rng(5)
    for _ in range(200):
        n = int(rng.integers(2, 25))
        p0 = rng.uniform(1000, 20000, size=n)
        pt = p0 * np.exp(rng.normal(0, 0.25, size=n))
        assert jevons(p0, pt) * jevons(pt, p0) / 100.0 == pytest.approx(100.0, rel=1e-9)


def test_carli_fails_time_reversal_upward_bias():
    """The reason APIx does not use Carli, asserted rather than asserted-in-prose."""
    p0, pt = [100.0, 100.0], [200.0, 50.0]
    assert carli(p0, pt) * carli(pt, p0) / 100.0 > 100.0


def test_jevons_transitivity():
    """I(0,1) * I(1,2) = I(0,2) exactly, in index points."""
    rng = np.random.default_rng(7)
    p0 = rng.uniform(2000, 9000, size=12)
    p1 = p0 * np.exp(rng.normal(0, 0.2, size=12))
    p2 = p1 * np.exp(rng.normal(0, 0.2, size=12))
    chained = jevons(p0, p1) / 100.0 * jevons(p1, p2)
    assert chained == pytest.approx(jevons(p0, p2), rel=1e-9)


def test_jevons_rejects_bad_input():
    with pytest.raises(ValueError):
        jevons([], [])
    with pytest.raises(ValueError):
        jevons([100.0, 0.0], [100.0, 100.0])
    with pytest.raises(ValueError):
        jevons([100.0], [100.0, 100.0])


def test_jevons_se_matches_delta_method():
    lr = log_relatives([1000, 2000, 3000], [1100, 2300, 3150])
    assert jevons_se(lr) == pytest.approx(delta_method_se(lr))


# ------------------------------------------------------------- availability

def test_blend_reduces_to_matched_when_fully_available():
    """A = 1 must change NOTHING. This is what makes the adjustment defensible."""
    assert blend(107.3, 145.9, 1.0) == pytest.approx(107.3)


def test_blend_converges_to_laf_when_nothing_available():
    assert blend(107.3, 145.9, 0.0) == pytest.approx(145.9)


def test_blend_is_monotone_and_continuous_in_a():
    vals = [blend(100.0, 160.0, a) for a in np.linspace(0, 1, 101)]
    assert all(vals[i] >= vals[i + 1] - 1e-12 for i in range(len(vals) - 1))
    assert max(abs(vals[i + 1] - vals[i]) for i in range(len(vals) - 1)) < 1.0


def test_blend_is_geometric_at_the_midpoint():
    assert blend(100.0, 144.0, 0.5) == pytest.approx(120.0)


def test_availability_ratio_clamps():
    assert availability_ratio(7, 5) == 1.0        # never exceeds 1
    assert availability_ratio(0, 5) > 0.0         # never exactly 0 (blend needs a log)
    assert availability_ratio(3, 0) == 1.0        # no reference bundle -> no adjustment


def test_availability_adjustment_catches_a_surge_a_matched_index_misses():
    """The central methodological claim, as an executable test.

    Cheap buckets close and the surviving expensive fare does not move. A
    matched index therefore reports no inflation; the adjusted index does.
    """
    rows = []
    for day, families in [("2026-05-01", ["SAVER", "MID", "TOP"]),
                          ("2026-05-02", ["TOP"])]:
        for flight in range(6):
            for fam, price in zip(["SAVER", "MID", "TOP"], [4000.0, 6000.0, 9000.0]):
                if fam not in families:
                    continue
                rows.append(dict(collected_date=day, departure_date="2026-05-08",
                                 route="DEL-BOM", carrier="6E", apw_days=7,
                                 flight_number=f"6E-{flight}", fare_family=fam,
                                 cabin="economy", stops=0, price=price,
                                 disposition="ACCEPTED"))
    q = pd.DataFrame(rows)
    w = WeightSet({"DEL-BOM": 1.0}, {"DEL-BOM": {"6E": 1.0}})
    cfg = dict(apw_windows=(7,), omega={7: 1.0}, bootstrap_draws=0,
               apply_dow_smoothing=False)

    naive = compute(q, w, MethodConfig(apply_availability_adjustment=False, **cfg))
    adjusted = compute(q, w, MethodConfig(apply_availability_adjustment=True, **cfg))

    naive_move = naive.headline["value"].iloc[-1] - 100.0
    adj_move = adjusted.headline["value"].iloc[-1] - 100.0

    assert naive_move == pytest.approx(0.0, abs=1e-9), "matched index should miss the surge"
    assert adj_move > 5.0, "adjusted index must register the surge"


# ---------------------------------------------------------------- smoothing

def test_seven_day_centred_gm_annihilates_a_weekly_cycle_exactly():
    """The day-of-week confound, removed exactly rather than approximately."""
    idx = pd.date_range("2026-01-01", periods=35, freq="D")
    cycle = 100 * np.exp(0.12 * np.sin(2 * np.pi * np.arange(35) / 7))
    smoothed = centred_geometric_ma(pd.Series(cycle, index=idx), 7)
    interior = smoothed.iloc[3:-3]
    assert interior.max() - interior.min() == pytest.approx(0.0, abs=1e-9)


def test_geometric_mean_matches_definition():
    assert geometric_mean([100.0, 121.0]) == pytest.approx(110.0)
    assert np.isnan(geometric_mean([]))


# -------------------------------------------------------------- aggregation

def test_apw_aggregation_renormalises_over_present_windows():
    """A missing window must not silently deflate the headline."""
    by_apw = pd.DataFrame({"period": ["d1", "d1"], "apw_days": [7, 30],
                           "value": [110.0, 120.0], "n_matched": [10, 10],
                           "coverage_pct": [100.0, 100.0]})
    out = aggregate_apw(by_apw, {1: 0.2, 7: 0.2, 15: 0.2, 30: 0.2, 45: 0.2})
    # Only two of five windows present: weights renormalise to 0.5 / 0.5.
    assert out["value"].iloc[0] == pytest.approx(115.0)


def test_suppressed_cell_weight_is_redistributed_pro_rata():
    """A cell below n_min is suppressed and its weight goes to its route-mates."""
    rows = []
    for day, idx in [("2026-05-01", 1.0), ("2026-05-02", 1.10)]:
        for flight in range(8):                       # 6E: plenty of matches
            rows.append(dict(collected_date=day, departure_date="2026-05-08",
                             route="DEL-BOM", carrier="6E", apw_days=7,
                             flight_number=f"6E-{flight}", fare_family="SAVER",
                             cabin="economy", stops=0, price=5000.0 * idx,
                             disposition="ACCEPTED"))
        for flight in range(2):                       # AI: only 2, below n_min=5
            rows.append(dict(collected_date=day, departure_date="2026-05-08",
                             route="DEL-BOM", carrier="AI", apw_days=7,
                             flight_number=f"AI-{flight}", fare_family="SAVER",
                             cabin="economy", stops=0, price=9000.0 * 2.0,
                             disposition="ACCEPTED"))
    q = pd.DataFrame(rows)
    w = WeightSet({"DEL-BOM": 1.0}, {"DEL-BOM": {"6E": 0.5, "AI": 0.5}})
    res = compute(q, w, MethodConfig(apw_windows=(7,), omega={7: 1.0}, bootstrap_draws=0,
                                     apply_dow_smoothing=False, n_min=5))
    # AI is suppressed, so the headline is 6E's index alone: exactly 110.
    assert res.headline["value"].iloc[-1] == pytest.approx(110.0)
    assert res.diagnostics["n_cells_suppressed"] == 2


def test_weights_are_injectable_and_change_the_answer():
    """PSD owns the weights: swapping them must move the number."""
    rows = []
    for day, a, b in [("2026-05-01", 1.0, 1.0), ("2026-05-02", 1.20, 1.00)]:
        for route, mult in [("DEL-BOM", a), ("DEL-BLR", b)]:
            for flight in range(6):
                rows.append(dict(collected_date=day, departure_date="2026-05-08",
                                 route=route, carrier="6E", apw_days=7,
                                 flight_number=f"6E-{route}-{flight}", fare_family="SAVER",
                                 cabin="economy", stops=0, price=5000.0 * mult,
                                 disposition="ACCEPTED"))
    q = pd.DataFrame(rows)
    cfg = MethodConfig(apw_windows=(7,), omega={7: 1.0}, bootstrap_draws=0,
                       apply_dow_smoothing=False)
    heavy = WeightSet({"DEL-BOM": 0.9, "DEL-BLR": 0.1},
                      {r: {"6E": 1.0} for r in ("DEL-BOM", "DEL-BLR")})
    light = WeightSet({"DEL-BOM": 0.1, "DEL-BLR": 0.9},
                      {r: {"6E": 1.0} for r in ("DEL-BOM", "DEL-BLR")})
    v_heavy = compute(q, heavy, cfg).headline["value"].iloc[-1]
    v_light = compute(q, light, cfg).headline["value"].iloc[-1]
    assert v_heavy == pytest.approx(100 + 0.9 * 20.0, abs=0.01)
    assert v_light == pytest.approx(100 + 0.1 * 20.0, abs=0.01)


# ------------------------------------------------------------- dual basis

def test_booking_and_travel_basis_differ_by_the_lead_time_lag():
    """Travel basis attributes a quote to departure date, not collection date."""
    rows = []
    for day in ["2026-05-01", "2026-05-02"]:
        for flight in range(6):
            rows.append(dict(collected_date=day, departure_date="2026-06-01",
                             route="DEL-BOM", carrier="6E", apw_days=30,
                             flight_number=f"6E-{flight}", fare_family="SAVER",
                             cabin="economy", stops=0, price=5000.0,
                             disposition="ACCEPTED"))
    q = pd.DataFrame(rows)
    w = WeightSet({"DEL-BOM": 1.0}, {"DEL-BOM": {"6E": 1.0}})
    base = dict(apw_windows=(30,), omega={30: 1.0}, bootstrap_draws=0,
                apply_dow_smoothing=False)
    book = compute(q, w, MethodConfig(basis="book", **base))
    travel = compute(q, w, MethodConfig(basis="travel", **base))
    assert list(book.headline["period"]) == ["2026-05-01", "2026-05-02"]
    assert list(travel.headline["period"]) == ["2026-06-01"]


# -------------------------------------------------------------- uncertainty

def test_bootstrap_is_deterministic_given_the_seed():
    """`make reproduce` printing zero diffs depends on exactly this."""
    blocks = {f"f{i}": np.random.default_rng(i).normal(0.05, 0.02, size=4) for i in range(30)}
    est = lambda lr: 100.0 * np.exp(lr.mean())  # noqa: E731
    a = flight_block_bootstrap(blocks, est, draws=200, seed=99)
    b = flight_block_bootstrap(blocks, est, draws=200, seed=99)
    assert a == b


def test_bootstrap_interval_brackets_the_point_estimate():
    blocks = {f"f{i}": np.random.default_rng(i).normal(0.04, 0.03, size=5) for i in range(40)}
    est = lambda lr: 100.0 * np.exp(lr.mean())  # noqa: E731
    point, se, lo, hi = flight_block_bootstrap(blocks, est, draws=400, seed=3)
    assert lo <= point <= hi
    assert se > 0


def test_engine_ci_brackets_published_value():
    """The published value must never sit outside its own confidence band."""
    rng = np.random.default_rng(2)
    rows = []
    for d in range(14):
        day = (pd.Timestamp("2026-05-01") + pd.Timedelta(days=d)).date().isoformat()
        for flight in range(8):
            for fam in ("SAVER", "MID", "TOP"):
                rows.append(dict(collected_date=day, departure_date="2026-06-01",
                                 route="DEL-BOM", carrier="6E", apw_days=7,
                                 flight_number=f"6E-{flight}", fare_family=fam,
                                 cabin="economy", stops=0,
                                 price=5000 * (1 + 0.004 * d) * (1 + rng.normal(0, 0.02)),
                                 disposition="ACCEPTED"))
    q = pd.DataFrame(rows)
    w = WeightSet({"DEL-BOM": 1.0}, {"DEL-BOM": {"6E": 1.0}})
    res = compute(q, w, MethodConfig(apw_windows=(7,), omega={7: 1.0}, bootstrap_draws=200))
    h = res.headline.dropna(subset=["ci_low"])
    assert len(h) > 0
    assert ((h["value"] >= h["ci_low"] - 1e-9) & (h["value"] <= h["ci_high"] + 1e-9)).all()


# ------------------------------------------------------------- determinism

def test_engine_is_deterministic():
    """Same inputs -> same outputs. Purity is the whole point of the package."""
    rng = np.random.default_rng(1)
    rows = []
    for d in range(8):
        day = (pd.Timestamp("2026-05-01") + pd.Timedelta(days=d)).date().isoformat()
        for flight in range(6):
            rows.append(dict(collected_date=day, departure_date="2026-06-01",
                             route="DEL-BOM", carrier="6E", apw_days=7,
                             flight_number=f"6E-{flight}", fare_family="SAVER",
                             cabin="economy", stops=0,
                             price=5000 * (1 + rng.normal(0, 0.02)),
                             disposition="ACCEPTED"))
    q = pd.DataFrame(rows)
    w = WeightSet({"DEL-BOM": 1.0}, {"DEL-BOM": {"6E": 1.0}})
    cfg = MethodConfig(apw_windows=(7,), omega={7: 1.0}, bootstrap_draws=50)
    a = compute(q, w, cfg).headline
    b = compute(q, w, cfg).headline
    pd.testing.assert_frame_equal(a, b)


def test_excluded_quotes_do_not_reach_the_index():
    rows = []
    for day, price in [("2026-05-01", 5000.0), ("2026-05-02", 5000.0)]:
        for flight in range(6):
            rows.append(dict(collected_date=day, departure_date="2026-06-01",
                             route="DEL-BOM", carrier="6E", apw_days=7,
                             flight_number=f"6E-{flight}", fare_family="SAVER",
                             cabin="economy", stops=0, price=price,
                             disposition="ACCEPTED"))
    # A wild EXCLUDED quote that would wreck the index if it were used.
    rows.append(dict(collected_date="2026-05-02", departure_date="2026-06-01",
                     route="DEL-BOM", carrier="6E", apw_days=7,
                     flight_number="6E-0", fare_family="SAVER", cabin="economy",
                     stops=0, price=999999.0, disposition="EXCLUDED"))
    q = pd.DataFrame(rows)
    w = WeightSet({"DEL-BOM": 1.0}, {"DEL-BOM": {"6E": 1.0}})
    res = compute(q, w, MethodConfig(apw_windows=(7,), omega={7: 1.0}, bootstrap_draws=0,
                                     apply_dow_smoothing=False))
    assert res.headline["value"].iloc[-1] == pytest.approx(100.0)


# ------------------------------- collapsed weights == staged aggregation

def test_effective_weights_equal_the_staged_aggregation():
    """The engine collapses stages 2-4 into one weight per cell to make the
    bootstrap cheap. Its docstring asserted this was covered by tests; it was
    not. It is now -- an unverified optimisation sitting under every published
    number is exactly the thing a reviewer should not have to take on trust.
    """
    from apix_index.aggregate import aggregate_apw, aggregate_carriers, aggregate_routes
    from apix_index.engine import _cell_indices, _effective_weights, _prepare, _smooth_cells

    rng = np.random.default_rng(4)
    rows = []
    routes, carriers, apws = ["DEL-BOM", "DEL-BLR", "BOM-BLR"], ["6E", "AI", "QP"], [7, 15, 30]
    for d in range(6):
        day = (pd.Timestamp("2026-05-01") + pd.Timedelta(days=d)).date().isoformat()
        for r in routes:
            for c in carriers:
                for a in apws:
                    for f in range(6):
                        for fam in ("SAVER", "MID", "TOP"):
                            rows.append(dict(collected_date=day, departure_date="2026-06-01",
                                             route=r, carrier=c, apw_days=a,
                                             flight_number=f"{c}-{f}", fare_family=fam,
                                             cabin="economy", stops=0,
                                             price=4000 * (1 + rng.normal(0, .05)),
                                             disposition="ACCEPTED"))
    q = pd.DataFrame(rows)
    w = WeightSet({r: v for r, v in zip(routes, [.5, .3, .2])},
                  {r: {"6E": .6, "AI": .3, "QP": .1} for r in routes})
    cfg = MethodConfig(apw_windows=(7, 15, 30), omega={7: .5, 15: .3, 30: .2},
                       bootstrap_draws=0, apply_dow_smoothing=False)

    cells = _smooth_cells(_cell_indices(_prepare(q, cfg), cfg)[0], cfg)
    omega = cfg.omega_vector()
    staged = aggregate_apw(aggregate_routes(aggregate_carriers(cells, w), w),
                           omega).set_index("period")["value"]
    eff = _effective_weights(cells, w, omega)

    for period, table in eff.items():
        total = sum(table.values())
        collapsed = sum(
            wt * float(cells[(cells.period == period) & (cells.route == r)
                             & (cells.carrier == c) & (cells.apw_days == a)]["adjusted"].iloc[0])
            for (r, c, a), wt in table.items()) / total
        assert collapsed == pytest.approx(float(staged[period]), abs=1e-9)


def test_prepare_returns_the_same_columns_on_both_paths():
    """The fast path and the de-duplicating path must agree on their output
    shape, or downstream code works only for whichever one it was tested on."""
    from apix_index.engine import _prepare
    rows = [dict(collected_date="2026-05-01", departure_date="2026-06-01", route="DEL-BOM",
                 carrier="6E", apw_days=7, flight_number=f"6E-{i}", fare_family="SAVER",
                 cabin="economy", stops=0, price=5000.0, disposition="ACCEPTED")
            for i in range(6)]
    q = pd.DataFrame(rows)
    cfg = MethodConfig()
    fast = _prepare(q, cfg)
    dedup = _prepare(pd.concat([q, q.iloc[[0]]], ignore_index=True), cfg)
    required = set(KAPPA) | {"period", "price", "n_sources"}
    assert required <= set(fast.columns)
    assert required <= set(dedup.columns)


def test_a_route_entering_after_the_base_period_is_reported_not_hidden():
    """Known limitation, pinned by a test so it cannot regress silently.

    The base period is the first period in the data. A route (or flight) that
    appears later has no base observation, so it is unmatched forever and is
    suppressed. There is no chain-linking / splice for new entrants yet; the
    correct behaviour today is that its weight is redistributed and the
    suppression is visible in diagnostics, NOT that it silently dilutes the
    index.
    """
    rows = []
    for d in range(10):
        day = (pd.Timestamp("2026-05-01") + pd.Timedelta(days=d)).date().isoformat()
        for f in range(6):
            rows.append(dict(collected_date=day, departure_date="2026-06-01",
                             route="DEL-BOM", carrier="6E", apw_days=7,
                             flight_number=f"6E-{f}", fare_family="SAVER", cabin="economy",
                             stops=0, price=5000.0, disposition="ACCEPTED"))
        if d >= 5:
            for f in range(6):
                rows.append(dict(collected_date=day, departure_date="2026-06-01",
                                 route="DEL-BLR", carrier="6E", apw_days=7,
                                 flight_number=f"6E-B{f}", fare_family="SAVER",
                                 cabin="economy", stops=0, price=7000.0,
                                 disposition="ACCEPTED"))
    q = pd.DataFrame(rows)
    w = WeightSet({"DEL-BOM": 0.5, "DEL-BLR": 0.5},
                  {r: {"6E": 1.0} for r in ("DEL-BOM", "DEL-BLR")})
    res = compute(q, w, MethodConfig(apw_windows=(7,), omega={7: 1.0}, bootstrap_draws=0,
                                     apply_dow_smoothing=False))
    late = res.cells[res.cells.route == "DEL-BLR"]
    assert len(late) > 0
    assert late["suppressed"].all(), "a late entrant has no base and must be suppressed"
    assert (res.by_apw["n_routes"] == 1).all(), "only the matched route contributes"
    assert res.diagnostics["n_cells_suppressed"] == len(late)
    # And the headline is still exactly the surviving route's own index.
    assert res.headline["value"].iloc[-1] == pytest.approx(100.0)


# ------------------------------------------------ base period / travel basis

def _ramping_panel() -> pd.DataFrame:
    """A panel collected from a fixed start, indexed on the TRAVEL basis.

    This is the shape real collection has: on the first collection day you can
    only see departures 1..45 days out, so an EARLY departure date can only
    ever have been observed at a SHORT advance-purchase window. A departure 45
    days after collection began is the first that can be seen at every window.
    """
    rows = []
    start = pd.Timestamp("2026-05-01")
    for d in range(60):
        collected = start + pd.Timedelta(days=d)
        for apw in (1, 7, 15, 30, 45):
            departure = collected + pd.Timedelta(days=apw)
            for f in range(6):
                rows.append(dict(
                    collected_date=collected.date().isoformat(),
                    departure_date=departure.date().isoformat(),
                    route="DEL-BOM", carrier="6E", apw_days=apw,
                    flight_number=f"6E-{f}", fare_family="SAVER", cabin="economy",
                    stops=0, price=5000.0 + 100.0 * apw, disposition="ACCEPTED"))
    return pd.DataFrame(rows)


def _cfg(**kw) -> MethodConfig:
    base = dict(apw_windows=(1, 7, 15, 30, 45), omega={1: 0.2, 7: 0.2, 15: 0.2, 30: 0.2, 45: 0.2},
                bootstrap_draws=0, apply_dow_smoothing=False)
    base.update(kw)
    return MethodConfig(**base)


def test_travel_basis_base_period_covers_every_lead_time_window():
    """Regression: the travel-basis headline collapsed into the T+1 series.

    Taking the first period as the base put a departure date in the base that
    could only have been observed at T+1. Every T+7..T+45 cell then failed to
    find a match in the base and was suppressed, so the published "headline"
    was the T+1 index wearing the headline's label, with omega inert.
    """
    weights = WeightSet({"DEL-BOM": 1.0}, {"DEL-BOM": {"6E": 1.0}})
    res = compute(_ramping_panel(), weights, _cfg(basis="travel"))

    windows = set(res.by_apw["apw_days"].astype(int))
    assert windows == {1, 7, 15, 30, 45}, (
        f"travel basis must index every lead-time window, got {sorted(windows)}")

    covered = res.headline["omega_covered"].max()
    assert covered == pytest.approx(1.0), (
        "at least one headline period must rest on the whole omega vector")


def test_book_basis_base_period_is_still_the_first_period():
    """The base rule must not disturb the book basis, where day one is full."""
    weights = WeightSet({"DEL-BOM": 1.0}, {"DEL-BOM": {"6E": 1.0}})
    panel = _ramping_panel()
    res = compute(panel, weights, _cfg(basis="book"))
    assert res.diagnostics["base_period"] == panel["collected_date"].min()


def test_pinned_base_period_is_honoured_and_validated():
    """A published series pins its base; a bad pin fails loudly, not silently."""
    weights = WeightSet({"DEL-BOM": 1.0}, {"DEL-BOM": {"6E": 1.0}})
    panel = _ramping_panel()
    pinned = "2026-05-20"
    res = compute(panel, weights, _cfg(basis="book", base_period=pinned))
    assert res.diagnostics["base_period"] == pinned

    with pytest.raises(ValueError, match="pinned base_period"):
        compute(panel, weights, _cfg(basis="book", base_period="1999-01-01"))
