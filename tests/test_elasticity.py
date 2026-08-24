"""Tests for the lead-time elasticity surface.

Found by the coverage review: this module -- one of only two genuinely fitted
models in the system, and the source of the most quotable number it produces
("the cheapest time to book DEL-BOM is tau* days out") -- had ZERO test
coverage. A published consumer statistic resting on an untested estimator is
exactly the thing that should not survive a review.

The central test is a ROUND TRIP: generate fares from a known log-quadratic
lead-time curve with a known trough, then assert the estimator recovers it.
That tests the estimator against ground truth rather than against itself.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apix_pipeline import elasticity


def _panel(tau_trough=26.0, curvature=0.085, n_flights=8, n_days=40,
           routes=("DEL-BOM", "DEL-BLR"), carriers=("6E", "AI"),
           taus=(1, 7, 15, 30, 45), noise=0.02, seed=0):
    """Fares generated from a KNOWN curve:  ln p = a + c*(ln tau - ln tau*)^2."""
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(n_days):
        day = pd.Timestamp("2026-01-01") + pd.Timedelta(days=d)
        for r in routes:
            for c in carriers:
                for tau in taus:
                    dep = day + pd.Timedelta(days=int(tau))
                    lead = curvature * (np.log(tau) - np.log(tau_trough)) ** 2
                    for f in range(n_flights):
                        rows.append(dict(
                            collected_date=day.date().isoformat(),
                            departure_date=dep.date().isoformat(),
                            route=r, carrier=c, apw_days=tau,
                            flight_number=f"{c}-{f}", fare_family="SAVER",
                            cabin="economy", stops=0,
                            price_T=float(np.exp(np.log(5000.0) + lead
                                                 + rng.normal(0, noise))),
                        ))
    return pd.DataFrame(rows)


# ------------------------------------------------------------- the round trip

def test_recovers_a_known_tau_star():
    """Ground-truth recovery, not self-consistency."""
    fit = elasticity.fit(_panel(tau_trough=26.0, curvature=0.085))
    assert fit.tau_star is not None
    assert fit.tau_star == pytest.approx(26.0, abs=2.0)


def test_recovers_a_known_curvature():
    fit = elasticity.fit(_panel(tau_trough=26.0, curvature=0.085))
    assert fit.beta2 == pytest.approx(0.085, abs=0.015)


def test_recovers_a_different_trough():
    """Move the truth and the estimate must follow it."""
    early = elasticity.fit(_panel(tau_trough=14.0, seed=1))
    late = elasticity.fit(_panel(tau_trough=35.0, seed=2))
    assert early.tau_star == pytest.approx(14.0, abs=2.5)
    assert late.tau_star == pytest.approx(35.0, abs=4.0)
    assert early.tau_star < late.tau_star


# ------------------------------------------------------------ the elasticity

def test_eta_has_the_right_shape_and_sign():
    """Negative below the trough, positive above, zero at it."""
    fit = elasticity.fit(_panel(tau_trough=26.0))
    assert float(fit.eta(1)) < 0, "booking later near departure costs more"
    assert float(fit.eta(45)) > 0, "past the trough, more lead time costs more"
    assert float(fit.eta(fit.tau_star)) == pytest.approx(0.0, abs=1e-6)


def test_eta_is_monotone_increasing_in_tau():
    fit = elasticity.fit(_panel())
    vals = [float(fit.eta(t)) for t in (1, 3, 7, 15, 30, 45, 60)]
    assert all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))


def test_eta_matches_its_closed_form():
    fit = elasticity.fit(_panel())
    for t in (1, 7, 26, 45):
        assert float(fit.eta(t)) == pytest.approx(
            fit.beta1 + 2 * fit.beta2 * np.log(t), abs=1e-12)


def test_tau_star_matches_its_closed_form():
    fit = elasticity.fit(_panel())
    assert fit.tau_star == pytest.approx(np.exp(-fit.beta1 / (2 * fit.beta2)), rel=1e-9)


# ------------------------------------------------------------- honest refusal

def test_declines_when_there_is_no_interior_minimum():
    """A monotone curve has no trough. Reporting one would be inventing it."""
    rng = np.random.default_rng(3)
    rows = []
    for d in range(30):
        day = pd.Timestamp("2026-01-01") + pd.Timedelta(days=d)
        for tau in (1, 7, 15, 30, 45):
            for f in range(8):
                rows.append(dict(
                    collected_date=day.date().isoformat(),
                    departure_date=(day + pd.Timedelta(days=tau)).date().isoformat(),
                    route="DEL-BOM", carrier="6E", apw_days=tau,
                    flight_number=f"6E-{f}", fare_family="SAVER", cabin="economy",
                    stops=0,
                    # strictly decreasing in tau -> concave, no interior minimum
                    price_T=float(np.exp(np.log(9000.0) - 0.25 * np.log(tau)
                                         + rng.normal(0, 0.02)))))
    fit = elasticity.fit(pd.DataFrame(rows))
    assert fit.tau_star is None
    assert fit.note
    assert "not identified" in fit.note or "no interior minimum" in fit.note


def test_rejects_too_small_a_sample():
    small = _panel(n_days=1, n_flights=1, routes=("DEL-BOM",), carriers=("6E",),
                   taus=(7,))
    with pytest.raises(ValueError, match="too few observations"):
        elasticity.fit(small)


def test_drops_nonpositive_prices_rather_than_taking_log_of_them():
    df = _panel(n_days=6)
    df.loc[df.index[:20], "price_T"] = 0.0
    fit = elasticity.fit(df)
    assert fit.n_obs == len(df) - 20


# ----------------------------------------------------- standard errors / fit

def test_standard_errors_are_clustered_by_flight():
    """Clustered SEs must exceed naive OLS SEs when flights are correlated."""
    fit = elasticity.fit(_panel())
    assert fit.n_clusters > 0
    assert fit.n_clusters < fit.n_obs, "clusters must be coarser than observations"
    assert fit.se_beta1 > 0 and fit.se_beta2 > 0
    assert np.isfinite(fit.se_beta1) and np.isfinite(fit.se_beta2)


def test_r_squared_is_sane():
    fit = elasticity.fit(_panel(noise=0.02))
    assert 0.0 <= fit.r_squared <= 1.0
    assert fit.r_squared > 0.5, "a clean generated curve should be well explained"


def test_per_route_fit_drops_the_route_fixed_effect():
    fit = elasticity.fit(_panel(), route="DEL-BOM")
    assert not any(k.startswith("route[") for k in fit.coefficients)
    assert fit.tau_star is not None


def test_fit_is_deterministic():
    df = _panel()
    a, b = elasticity.fit(df), elasticity.fit(df)
    assert a.coefficients == b.coefficients
    assert a.tau_star == b.tau_star


def test_holiday_regressor_is_included_when_supplied():
    df = _panel(n_days=30)
    holidays = sorted(df["departure_date"].unique())[:5]
    fit = elasticity.fit(df, holidays=holidays)
    assert "holiday" in fit.coefficients


# -------------------------------------------------------------- the surface

def test_surface_returns_a_band_per_window():
    fit = elasticity.fit(_panel())
    surf = elasticity.surface(fit, [1, 7, 15, 30, 45])
    assert list(surf["apw_days"]) == [1, 7, 15, 30, 45]
    np.testing.assert_allclose(surf["eta"].to_numpy(),
                               fit.eta([1, 7, 15, 30, 45]), rtol=1e-12)
    # Without a covariance matrix the band is NaN rather than a fabricated zero.
    assert surf["eta_se"].isna().all()


# ----------------------------------------------------------- the fare ladder

def test_fare_ladder_recovers_a_known_number_of_buckets():
    """The Gaussian mixture must find the discrete RBD structure."""
    rng = np.random.default_rng(5)
    prices = np.concatenate([
        np.exp(np.log(4000) + rng.normal(0, 0.02, 300)),
        np.exp(np.log(7000) + rng.normal(0, 0.02, 300)),
        np.exp(np.log(12000) + rng.normal(0, 0.02, 300)),
    ])
    df = pd.DataFrame({"route": "DEL-BOM", "carrier": "6E", "price_T": prices})
    out = elasticity.fare_ladder(df, "DEL-BOM", "6E")
    assert out["n_components"] == 3
    fares = sorted(b["fare_inr"] for b in out["buckets"])
    assert fares[0] == pytest.approx(4000, rel=0.05)
    assert fares[1] == pytest.approx(7000, rel=0.05)
    assert fares[2] == pytest.approx(12000, rel=0.05)


def test_fare_ladder_declines_on_a_thin_sample():
    df = pd.DataFrame({"route": ["DEL-BOM"] * 10, "carrier": ["6E"] * 10,
                       "price_T": np.linspace(4000, 9000, 10)})
    out = elasticity.fare_ladder(df, "DEL-BOM", "6E")
    assert "error" in out
    assert out["n_obs"] == 10


def test_fare_ladder_weights_sum_to_one():
    rng = np.random.default_rng(6)
    prices = np.concatenate([np.exp(np.log(4000) + rng.normal(0, 0.03, 200)),
                             np.exp(np.log(9000) + rng.normal(0, 0.03, 100))])
    df = pd.DataFrame({"route": "DEL-BOM", "carrier": "6E", "price_T": prices})
    out = elasticity.fare_ladder(df, "DEL-BOM", "6E")
    assert sum(b["weight"] for b in out["buckets"]) == pytest.approx(1.0)
