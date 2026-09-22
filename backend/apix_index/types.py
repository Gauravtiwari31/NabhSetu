"""Pure types for the Nabhsetu statistical engine.

This package has no I/O, database, network, or clock. The same quotes, weights,
and method config must always produce the same numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal, Mapping, Sequence

KAPPA: tuple[str, ...] = (
    "route",
    "carrier",
    "apw_days",
    "flight_number",
    "fare_family",
    "cabin",
    "stops",
)
CELL: tuple[str, ...] = ("route", "carrier", "apw_days")
FLIGHT: tuple[str, ...] = ("route", "carrier", "apw_days", "flight_number")

Basis = Literal["book", "travel"]
Variant = Literal["B", "T", "A"]
Frequency = Literal["daily", "weekly", "monthly"]
PUBLISHABLE = frozenset({"ACCEPTED", "WINSORISED", "accepted", "winsorised"})

OMEGA_PRESETS: dict[str, dict[int, Decimal]] = {
    "uniform": {1: Decimal("0.2"), 7: Decimal("0.2"), 15: Decimal("0.2"), 30: Decimal("0.2"), 45: Decimal("0.2")},
    "near_term": {
        1: Decimal("0.35"),
        7: Decimal("0.30"),
        15: Decimal("0.20"),
        30: Decimal("0.10"),
        45: Decimal("0.05"),
    },
    "leisure": {
        1: Decimal("0.05"),
        7: Decimal("0.10"),
        15: Decimal("0.20"),
        30: Decimal("0.30"),
        45: Decimal("0.35"),
    },
}


def _as_decimal(value: Decimal | int | float | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _normalise_share(mapping: Mapping[object, Decimal | int | float | str]) -> dict:
    items = {key: _as_decimal(value) for key, value in mapping.items()}
    total = sum(items.values(), Decimal("0"))
    if total <= 0:
        raise ValueError("weights must sum to a positive number")
    return {key: value / total for key, value in items.items()}


@dataclass(frozen=True)
class MethodConfig:
    method_version: str = "1.0.0"
    apw_windows: Sequence[int] = (1, 7, 15, 30, 45)
    n_min: int = 5
    tukey_k: Decimal = Decimal("3.0")
    hampel_z: Decimal = Decimal("3.5")
    jump_sigma: Decimal = Decimal("3.0")
    dow_window: int = 7
    bootstrap_draws: int = 200
    bootstrap_seed: int = 20260822
    ci_level: Decimal = Decimal("0.90")
    omega: dict[int, Decimal] | None = None
    omega_preset: str = "uniform"
    variant: Variant = "T"
    basis: Basis = "book"
    apply_availability_adjustment: bool = True
    apply_dow_smoothing: bool = True
    # Reference period for the matched-model comparison. Unset, the engine
    # picks the earliest best-covered period; pin it once a series is
    # published so new data cannot rewrite the history.
    base_period: str | None = None

    def omega_vector(self) -> dict[int, Decimal]:
        if self.omega:
            raw = {int(key): _as_decimal(value) for key, value in self.omega.items()}
            total = sum(raw.values(), Decimal("0"))
            if total <= 0:
                raise ValueError("omega weights must sum to a positive number")
            return {key: value / total for key, value in raw.items()}
        preset = OMEGA_PRESETS.get(self.omega_preset)
        if preset is not None:
            selected = {window: preset[window] for window in self.apw_windows if window in preset}
            if selected:
                total = sum(selected.values(), Decimal("0"))
                return {key: value / total for key, value in selected.items()}
        n = len(self.apw_windows)
        share = Decimal("1") / Decimal(n)
        return {int(window): share for window in self.apw_windows}


@dataclass(frozen=True)
class WeightSet:
    route_weights: dict[str, Decimal]
    carrier_weights: dict[str, dict[str, Decimal]]
    weights_version: str = "v1"
    source: str = "declared"

    @classmethod
    def from_mapping(
        cls,
        route_weights: Mapping[str, Decimal | int | float | str],
        carrier_weights: Mapping[str, Mapping[str, Decimal | int | float | str]],
        *,
        weights_version: str = "v1",
        source: str = "declared",
    ) -> WeightSet:
        routes = {route: _as_decimal(weight) for route, weight in route_weights.items()}
        carriers = {
            route: {carrier: _as_decimal(weight) for carrier, weight in table.items()}
            for route, table in carrier_weights.items()
        }
        return cls(routes, carriers, weights_version=weights_version, source=source)

    def normalised_routes(self, present: Sequence[str]) -> dict[str, Decimal]:
        sub = {route: self.route_weights.get(route, Decimal("0")) for route in present}
        total = sum(sub.values(), Decimal("0"))
        if total <= 0:
            if not present:
                return {}
            share = Decimal("1") / Decimal(len(present))
            return {route: share for route in present}
        return {route: weight / total for route, weight in sub.items()}

    def normalised_carriers(self, route: str, present: Sequence[str]) -> dict[str, Decimal]:
        table = self.carrier_weights.get(route, {})
        sub = {carrier: table.get(carrier, Decimal("0")) for carrier in present}
        total = sum(sub.values(), Decimal("0"))
        if total <= 0:
            if not present:
                return {}
            share = Decimal("1") / Decimal(len(present))
            return {carrier: share for carrier in present}
        return {carrier: weight / total for carrier, weight in sub.items()}

    def basket_route_total(self) -> Decimal:
        return sum(self.route_weights.values(), Decimal("0"))


@dataclass(frozen=True)
class Quote:
    collected_date: date
    departure_date: date
    route: str
    carrier: str
    apw_days: int
    flight_number: str
    fare_family: str
    cabin: str
    stops: int
    price: Decimal
    is_sold_out: bool = False
    disposition: str = "ACCEPTED"
    observation_id: str | None = None
    n_sources: int = 1

    def kappa(self) -> tuple:
        return (
            self.route,
            self.carrier,
            int(self.apw_days),
            self.flight_number,
            self.fare_family,
            self.cabin,
            int(self.stops),
        )

    def flight_key(self) -> tuple:
        return (self.route, self.carrier, int(self.apw_days), self.flight_number)

    def cell_key(self) -> tuple:
        return (self.route, self.carrier, int(self.apw_days))

    def period_for(self, basis: Basis) -> str:
        chosen = self.collected_date if basis == "book" else self.departure_date
        return chosen.isoformat()


@dataclass
class CellResult:
    period: str
    route: str
    carrier: str
    apw_days: int
    matched: Decimal | None
    laf: Decimal | None
    availability: Decimal
    adjusted: Decimal | None
    adjusted_raw: Decimal | None
    n_matched: int
    n_quotes: int
    n_families: int
    suppressed: bool


@dataclass
class RouteIndex:
    period: str
    route: str
    apw_days: int
    value: Decimal
    n_carriers: int
    n_matched: int
    carrier_weight_sum: Decimal


@dataclass
class ApwIndex:
    period: str
    apw_days: int
    value: Decimal
    n_routes: int
    n_matched: int
    coverage_pct: Decimal


@dataclass
class HeadlinePoint:
    period: str
    value: Decimal
    se: Decimal | None
    ci_low: Decimal | None
    ci_high: Decimal | None
    n_quotes: int
    n_cells: int
    n_matched: int
    n_apw: int
    coverage_pct: Decimal
    omega_covered: Decimal
    value_unsmoothed: Decimal | None = None


@dataclass
class IndexResult:
    headline: list[HeadlinePoint]
    by_apw: list[ApwIndex]
    by_route: list[RouteIndex]
    cells: list[CellResult]
    diagnostics: dict = field(default_factory=dict)
    method_version: str = "1.0.0"
    weights_version: str = "v1"
    basis: str = "book"
    variant: str = "T"
    omega_preset: str = "uniform"

    def headline_map(self) -> dict[str, HeadlinePoint]:
        return {point.period: point for point in self.headline}
