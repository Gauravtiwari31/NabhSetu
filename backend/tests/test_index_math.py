"""Unit and property tests for Decimal-stable APIx arithmetic."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from random import Random

import pytest

from apix_index import (
    MethodConfig,
    WeightSet,
    aggregate_apw,
    availability_ratio,
    blend,
    carli,
    centred_geometric_ma,
    compute,
    dutot,
    geometric_mean,
    jevons,
    jevons_se,
    log_relatives,
)
from apix_index.types import ApwIndex
from apix_index.uncertainty import delta_method_se, flight_block_bootstrap


def test_jevons_hand_computed() -> None:
    assert float(jevons([100, 100], [200, 50])) == pytest.approx(100.0)


def test_jevons_uniform_price_change() -> None:
    p0 = [1000.0, 2500.0, 7000.0]
    pt = [price * 1.10 for price in p0]
    assert float(jevons(p0, pt)) == pytest.approx(110.0)
    assert float(dutot(p0, pt)) == pytest.approx(110.0)
    assert float(carli(p0, pt)) == pytest.approx(110.0)


def test_am_gm_ordering_dutot_jevons_carli() -> None:
    rng = Random(11)
    for _ in range(50):
        n = rng.randint(2, 12)
        p0 = [rng.uniform(1000, 20000) for _ in range(n)]
        pt = [price * (2.71828 ** rng.uniform(-0.3, 0.3)) for price in p0]
        assert float(carli(p0, pt)) >= float(jevons(p0, pt)) - 1e-6


def test_jevons_satisfies_time_reversal() -> None:
    rng = Random(5)
    for _ in range(40):
        n = rng.randint(2, 10)
        p0 = [rng.uniform(1000, 20000) for _ in range(n)]
        pt = [price * (2.71828 ** rng.uniform(-0.25, 0.25)) for price in p0]
        assert float(jevons(p0, pt) * jevons(pt, p0) / Decimal("100")) == pytest.approx(100.0, rel=1e-6)


def test_carli_fails_time_reversal_upward_bias() -> None:
    p0, pt = [100.0, 100.0], [200.0, 50.0]
    assert float(carli(p0, pt) * carli(pt, p0) / Decimal("100")) > 100.0


def test_jevons_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        jevons([], [])
    with pytest.raises(ValueError):
        jevons([100.0, 0.0], [100.0, 100.0])
    with pytest.raises(ValueError):
        jevons([100.0], [100.0, 100.0])


def test_jevons_se_matches_delta_method() -> None:
    relatives = log_relatives([1000, 2000, 3000], [1100, 2300, 3150])
    assert float(jevons_se(relatives) or 0) == pytest.approx(delta_method_se(relatives))


def test_blend_identities() -> None:
    assert float(blend(107.3, 145.9, 1.0) or 0) == pytest.approx(107.3)
    assert float(blend(107.3, 145.9, 0.0) or 0) == pytest.approx(145.9)
    assert float(blend(100.0, 144.0, 0.5) or 0) == pytest.approx(120.0)


def test_availability_ratio_clamps() -> None:
    assert availability_ratio(7, 5) == Decimal("1")
    assert availability_ratio(0, 5) > 0
    assert availability_ratio(3, 0) == Decimal("1")


def test_geometric_mean_matches_definition() -> None:
    assert float(geometric_mean([100.0, 121.0]) or 0) == pytest.approx(110.0)
    assert geometric_mean([]) is None


def test_seven_day_centred_gm_annihilates_a_weekly_cycle() -> None:
    import math

    cycle = [Decimal(str(100 * math.exp(0.12 * math.sin(2 * math.pi * index / 7)))) for index in range(35)]
    smoothed = centred_geometric_ma(cycle, 7)
    interior = smoothed[3:-3]
    assert float(max(interior) - min(interior)) == pytest.approx(0.0, abs=1e-5)


def _quotes(rows: list[dict]) -> list[dict]:
    return rows


def test_availability_adjustment_catches_a_surge_a_matched_index_misses() -> None:
    rows = []
    for day, families in [("2026-05-01", ["SAVER", "MID", "TOP"]), ("2026-05-02", ["TOP"])]:
        for flight in range(6):
            for family, price in zip(["SAVER", "MID", "TOP"], [4000.0, 6000.0, 9000.0]):
                if family not in families:
                    continue
                rows.append(
                    dict(
                        collected_date=day,
                        departure_date="2026-05-08",
                        route="DEL-BOM",
                        carrier="6E",
                        apw_days=7,
                        flight_number=f"6E-{flight}",
                        fare_family=family,
                        cabin="economy",
                        stops=0,
                        price=price,
                        disposition="ACCEPTED",
                    )
                )
    weights = WeightSet.from_mapping({"DEL-BOM": 1.0}, {"DEL-BOM": {"6E": 1.0}})
    cfg = dict(apw_windows=(7,), omega={7: Decimal("1")}, bootstrap_draws=0, apply_dow_smoothing=False)
    naive = compute(rows, weights, MethodConfig(apply_availability_adjustment=False, **cfg))
    adjusted = compute(rows, weights, MethodConfig(apply_availability_adjustment=True, **cfg))
    naive_move = float(naive.headline[-1].value) - 100.0
    adj_move = float(adjusted.headline[-1].value) - 100.0
    assert naive_move == pytest.approx(0.0, abs=1e-6)
    assert adj_move > 5.0


def test_apw_aggregation_renormalises_over_present_windows() -> None:
    by_apw = [
        ApwIndex("d1", 7, Decimal("110"), 1, 10, Decimal("100")),
        ApwIndex("d1", 30, Decimal("120"), 1, 10, Decimal("100")),
    ]
    out = aggregate_apw(by_apw, {1: Decimal("0.2"), 7: Decimal("0.2"), 15: Decimal("0.2"), 30: Decimal("0.2"), 45: Decimal("0.2")})
    assert float(out[0]["value"]) == pytest.approx(115.0)


def test_suppressed_cell_weight_is_redistributed_pro_rata() -> None:
    rows = []
    for day, idx in [("2026-05-01", 1.0), ("2026-05-02", 1.10)]:
        for flight in range(8):
            rows.append(
                dict(
                    collected_date=day,
                    departure_date="2026-05-08",
                    route="DEL-BOM",
                    carrier="6E",
                    apw_days=7,
                    flight_number=f"6E-{flight}",
                    fare_family="SAVER",
                    cabin="economy",
                    stops=0,
                    price=5000.0 * idx,
                    disposition="ACCEPTED",
                )
            )
        for flight in range(2):
            rows.append(
                dict(
                    collected_date=day,
                    departure_date="2026-05-08",
                    route="DEL-BOM",
                    carrier="AI",
                    apw_days=7,
                    flight_number=f"AI-{flight}",
                    fare_family="SAVER",
                    cabin="economy",
                    stops=0,
                    price=9000.0 * 2.0,
                    disposition="ACCEPTED",
                )
            )
    weights = WeightSet.from_mapping({"DEL-BOM": 1.0}, {"DEL-BOM": {"6E": 0.5, "AI": 0.5}})
    result = compute(
        rows,
        weights,
        MethodConfig(apw_windows=(7,), omega={7: Decimal("1")}, bootstrap_draws=0, apply_dow_smoothing=False, n_min=5),
    )
    assert float(result.headline[-1].value) == pytest.approx(110.0)
    assert result.diagnostics["n_cells_suppressed"] == 2


def test_weights_are_injectable_and_change_the_answer() -> None:
    rows = []
    for day, a, b in [("2026-05-01", 1.0, 1.0), ("2026-05-02", 1.20, 1.00)]:
        for route, mult in [("DEL-BOM", a), ("DEL-BLR", b)]:
            for flight in range(6):
                rows.append(
                    dict(
                        collected_date=day,
                        departure_date="2026-05-08",
                        route=route,
                        carrier="6E",
                        apw_days=7,
                        flight_number=f"6E-{route}-{flight}",
                        fare_family="SAVER",
                        cabin="economy",
                        stops=0,
                        price=5000.0 * mult,
                        disposition="ACCEPTED",
                    )
                )
    cfg = MethodConfig(apw_windows=(7,), omega={7: Decimal("1")}, bootstrap_draws=0, apply_dow_smoothing=False)
    heavy = WeightSet.from_mapping({"DEL-BOM": 0.9, "DEL-BLR": 0.1}, {route: {"6E": 1.0} for route in ("DEL-BOM", "DEL-BLR")})
    light = WeightSet.from_mapping({"DEL-BOM": 0.1, "DEL-BLR": 0.9}, {route: {"6E": 1.0} for route in ("DEL-BOM", "DEL-BLR")})
    v_heavy = float(compute(rows, heavy, cfg).headline[-1].value)
    v_light = float(compute(rows, light, cfg).headline[-1].value)
    assert v_heavy == pytest.approx(100 + 0.9 * 20.0, abs=0.05)
    assert v_light == pytest.approx(100 + 0.1 * 20.0, abs=0.05)


def test_booking_and_travel_basis_differ() -> None:
    rows = []
    for day in ["2026-05-01", "2026-05-02"]:
        for flight in range(6):
            rows.append(
                dict(
                    collected_date=day,
                    departure_date="2026-06-01",
                    route="DEL-BOM",
                    carrier="6E",
                    apw_days=30,
                    flight_number=f"6E-{flight}",
                    fare_family="SAVER",
                    cabin="economy",
                    stops=0,
                    price=5000.0,
                    disposition="ACCEPTED",
                )
            )
    weights = WeightSet.from_mapping({"DEL-BOM": 1.0}, {"DEL-BOM": {"6E": 1.0}})
    base = dict(apw_windows=(30,), omega={30: Decimal("1")}, bootstrap_draws=0, apply_dow_smoothing=False)
    book = compute(rows, weights, MethodConfig(basis="book", **base))
    travel = compute(rows, weights, MethodConfig(basis="travel", **base))
    assert [point.period for point in book.headline] == ["2026-05-01", "2026-05-02"]
    assert [point.period for point in travel.headline] == ["2026-06-01"]


def test_excluded_quotes_do_not_reach_the_index() -> None:
    rows = []
    for day, price in [("2026-05-01", 5000.0), ("2026-05-02", 5000.0)]:
        for flight in range(6):
            rows.append(
                dict(
                    collected_date=day,
                    departure_date="2026-06-01",
                    route="DEL-BOM",
                    carrier="6E",
                    apw_days=7,
                    flight_number=f"6E-{flight}",
                    fare_family="SAVER",
                    cabin="economy",
                    stops=0,
                    price=price,
                    disposition="ACCEPTED",
                )
            )
    rows.append(
        dict(
            collected_date="2026-05-02",
            departure_date="2026-06-01",
            route="DEL-BOM",
            carrier="6E",
            apw_days=7,
            flight_number="6E-0",
            fare_family="SAVER",
            cabin="economy",
            stops=0,
            price=999999.0,
            disposition="EXCLUDED",
        )
    )
    weights = WeightSet.from_mapping({"DEL-BOM": 1.0}, {"DEL-BOM": {"6E": 1.0}})
    result = compute(
        rows,
        weights,
        MethodConfig(apw_windows=(7,), omega={7: Decimal("1")}, bootstrap_draws=0, apply_dow_smoothing=False),
    )
    assert float(result.headline[-1].value) == pytest.approx(100.0)


def test_late_entrant_is_suppressed() -> None:
    rows = []
    start = date(2026, 5, 1)
    for offset in range(10):
        day = (start + timedelta(days=offset)).isoformat()
        for flight in range(6):
            rows.append(
                dict(
                    collected_date=day,
                    departure_date="2026-06-01",
                    route="DEL-BOM",
                    carrier="6E",
                    apw_days=7,
                    flight_number=f"6E-{flight}",
                    fare_family="SAVER",
                    cabin="economy",
                    stops=0,
                    price=5000.0,
                    disposition="ACCEPTED",
                )
            )
        if offset >= 5:
            for flight in range(6):
                rows.append(
                    dict(
                        collected_date=day,
                        departure_date="2026-06-01",
                        route="DEL-BLR",
                        carrier="6E",
                        apw_days=7,
                        flight_number=f"6E-B{flight}",
                        fare_family="SAVER",
                        cabin="economy",
                        stops=0,
                        price=7000.0,
                        disposition="ACCEPTED",
                    )
                )
    weights = WeightSet.from_mapping(
        {"DEL-BOM": 0.5, "DEL-BLR": 0.5},
        {route: {"6E": 1.0} for route in ("DEL-BOM", "DEL-BLR")},
    )
    result = compute(
        rows,
        weights,
        MethodConfig(apw_windows=(7,), omega={7: Decimal("1")}, bootstrap_draws=0, apply_dow_smoothing=False),
    )
    late = [cell for cell in result.cells if cell.route == "DEL-BLR"]
    assert late
    assert all(cell.suppressed for cell in late)
    assert all(row.n_routes == 1 for row in result.by_apw)
    assert float(result.headline[-1].value) == pytest.approx(100.0)


def test_engine_is_deterministic() -> None:
    rng = Random(1)
    rows = []
    start = date(2026, 5, 1)
    for offset in range(8):
        day = (start + timedelta(days=offset)).isoformat()
        for flight in range(6):
            rows.append(
                dict(
                    collected_date=day,
                    departure_date="2026-06-01",
                    route="DEL-BOM",
                    carrier="6E",
                    apw_days=7,
                    flight_number=f"6E-{flight}",
                    fare_family="SAVER",
                    cabin="economy",
                    stops=0,
                    price=5000 * (1 + rng.uniform(-0.02, 0.02)),
                    disposition="ACCEPTED",
                )
            )
    weights = WeightSet.from_mapping({"DEL-BOM": 1.0}, {"DEL-BOM": {"6E": 1.0}})
    cfg = MethodConfig(apw_windows=(7,), omega={7: Decimal("1")}, bootstrap_draws=20)
    first = compute(rows, weights, cfg).headline
    second = compute(rows, weights, cfg).headline
    assert [point.value for point in first] == [point.value for point in second]
    assert [point.ci_low for point in first] == [point.ci_low for point in second]


def test_bootstrap_is_deterministic_given_the_seed() -> None:
    rng = Random(0)
    blocks = {f"f{i}": [rng.gauss(0.05, 0.02) for _ in range(4)] for i in range(20)}
    estimator = lambda relatives: float(jevons(  # noqa: E731
        [100 for _ in relatives],
        [100 * (2.718281828 ** rel) for rel in relatives],
    )) if False else 100.0 * (2.718281828 ** (sum(relatives) / len(relatives)))
    first = flight_block_bootstrap(blocks, estimator, draws=80, seed=99)
    second = flight_block_bootstrap(blocks, estimator, draws=80, seed=99)
    assert first == second


def test_base_period_is_one_hundred() -> None:
    rows = []
    for flight in range(6):
        rows.append(
            dict(
                collected_date="2026-05-01",
                departure_date="2026-05-08",
                route="DEL-BOM",
                carrier="6E",
                apw_days=7,
                flight_number=f"6E-{flight}",
                fare_family="SAVER",
                cabin="economy",
                stops=0,
                price=5000.0,
                disposition="ACCEPTED",
            )
        )
    weights = WeightSet.from_mapping({"DEL-BOM": 1.0}, {"DEL-BOM": {"6E": 1.0}})
    result = compute(
        rows,
        weights,
        MethodConfig(apw_windows=(7,), omega={7: Decimal("1")}, bootstrap_draws=0, apply_dow_smoothing=False),
    )
    assert float(result.headline[0].value) == pytest.approx(100.0)
