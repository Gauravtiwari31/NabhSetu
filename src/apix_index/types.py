"""Types for the APIx index engine.

This package is PURE: no I/O, no database, no network, no clock. It takes a
DataFrame of cleaned quotes, a weight set and a method config, and returns
index numbers. Purity is what makes it unit-testable against IMF CPI Manual
worked examples, and what lets MoSPI's Price Statistics Division run it on
their own data without adopting the rest of our stack.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Sequence

import pandas as pd

# --- The matching key kappa (Part 4, section 1.1) -------------------------
# Two quotes are the same product in two periods iff they agree on all of these.
# Matching on flight_number rather than departure_date is deliberate: it tracks
# the same flight in the schedule across weeks, the airline analogue of tracking
# the same SKU in a shop.
KAPPA: List[str] = [
    "route", "carrier", "apw_days", "flight_number", "fare_family", "cabin", "stops",
]

# The elementary aggregate cell g = (r, c, tau).
CELL: List[str] = ["route", "carrier", "apw_days"]

# A flight, for LAF and for bootstrap blocking.
FLIGHT: List[str] = ["route", "carrier", "apw_days", "flight_number"]

Basis = Literal["book", "travel"]
Variant = Literal["B", "T", "A"]
Frequency = Literal["daily", "weekly", "monthly"]


@dataclass(frozen=True)
class MethodConfig:
    """Everything that governs the arithmetic. Stamped as `method_version`."""
    method_version: str = "1.0.0"
    apw_windows: Sequence[int] = (1, 7, 15, 30, 45)
    n_min: int = 5
    tukey_k: float = 3.0
    hampel_z: float = 3.5
    jump_sigma: float = 3.0
    dow_window: int = 7
    bootstrap_draws: int = 500
    bootstrap_seed: int = 20260822
    ci_level: float = 0.90
    omega: Optional[Dict[int, float]] = None
    omega_preset: str = "uniform"
    variant: Variant = "T"
    basis: Basis = "book"
    apply_availability_adjustment: bool = True
    apply_dow_smoothing: bool = True
    # Reference period for the matched-model comparison. Left unset the engine
    # picks the earliest BEST-COVERED period (see engine._choose_base_period).
    # Pin it once a series is published: a base that moves as new data lands
    # silently rewrites history, which an official index may not do.
    base_period: Optional[str] = None
    # A headline period must rest on at least this share of the lead-time
    # weight vector to be published. Below it the number is arithmetically
    # fine but is not the thing its label claims: it is one or two windows
    # standing in for the whole booking curve.
    min_omega_covered: float = 0.60
    # Chain-link onto an external index already published on an earlier base,
    # so this series can be presented on that base (e.g. 2024=100). APIx cannot
    # be BASED on 2024: the matched-model comparison needs base-period quotes to
    # match against, and no 2024 fare quotes exist or can be back-collected.
    #
    # The link is one multiplicative constant applied to every published level.
    # It moves the LEVEL and never a relative -- period on period and cell on
    # cell are identical before and after. It is a SPLICE, not a measurement:
    # it asserts the external series' inflation across the gap. Publish the
    # linked level as linked, and keep `value_native` beside it.
    link_factor: Optional[float] = None
    link_label: Optional[str] = None

    def omega_vector(self) -> Dict[int, float]:
        """Lead-time weights, defaulting to uniform over the configured windows."""
        if self.omega:
            total = float(sum(self.omega.values()))
            if total <= 0:
                raise ValueError("omega weights must sum to a positive number")
            return {int(k): float(v) / total for k, v in self.omega.items()}
        n = len(self.apw_windows)
        return {int(t): 1.0 / n for t in self.apw_windows}


@dataclass(frozen=True)
class WeightSet:
    """Weights are an INJECTED PARAMETER, never derived inside the engine.

    This is the whole point of Part 4 Stage 3: PSD, not the team, owns the
    weights. `phi` is the within-route carrier weight, `w_r` the route weight.
    `source` and `version` are stamped onto every published number so that a
    figure computed under one weight vector is never confused with another.
    """
    route_weights: Dict[str, float]                     # w_r, by "DEL-BOM"
    carrier_weights: Dict[str, Dict[str, float]]        # phi_{c|r}: route -> carrier -> w
    weights_version: str = "v1"
    source: str = "derived"

    def normalised_routes(self, present: Sequence[str]) -> Dict[str, float]:
        """Renormalise w_r over the routes actually present in this run."""
        sub = {r: self.route_weights.get(r, 0.0) for r in present}
        total = sum(sub.values())
        if total <= 0:
            # No supplied weights for these routes: fall back to equal weighting
            # and let the caller see it in the coverage ledger.
            return {r: 1.0 / len(present) for r in present} if present else {}
        return {r: v / total for r, v in sub.items()}

    def normalised_carriers(self, route: str, present: Sequence[str]) -> Dict[str, float]:
        """Renormalise phi over the carriers whose cells survived suppression.

        This IS the pro-rata redistribution required by Part 4 Stage 1: a
        suppressed cell's weight goes to the remaining cells within the same
        route, exactly the mechanism MoSPI uses when an item is unavailable in
        a market.
        """
        table = self.carrier_weights.get(route, {})
        sub = {c: table.get(c, 0.0) for c in present}
        total = sum(sub.values())
        if total <= 0:
            return {c: 1.0 / len(present) for c in present} if present else {}
        return {c: v / total for c, v in sub.items()}


@dataclass
class IndexResult:
    """What the engine returns. Every frame is tidy and directly publishable."""
    headline: pd.DataFrame          # period, value, se, ci_low, ci_high, n_quotes, n_cells, coverage_pct
    by_apw: pd.DataFrame            # period, apw_days, value
    by_route: pd.DataFrame          # period, route, apw_days, value
    cells: pd.DataFrame             # period, route, carrier, apw_days, matched, laf, availability, adjusted, n_matched, suppressed
    diagnostics: Dict[str, object] = field(default_factory=dict)
    method_version: str = "1.0.0"
    weights_version: str = "v1"
    basis: str = "book"
    variant: str = "T"
    omega_preset: str = "uniform"
