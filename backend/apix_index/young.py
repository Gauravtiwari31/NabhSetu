"""Young / modified Laspeyres aggregation of elementary indices.

    I = Σ w_i * I_i    with weights renormalised over the cells that survive.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from apix_index.decimal_math import to_decimal
from apix_index.types import ApwIndex, CellResult, RouteIndex, WeightSet


def compute_young(component_indices: list, weights: list) -> Decimal:
    """Return the Young aggregate of elementary indices."""
    if len(component_indices) != len(weights):
        raise ValueError("component indices and weights must have the same length")
    if not component_indices:
        raise ValueError("cannot aggregate an empty set of components")
    values = [to_decimal(value) for value in component_indices]
    shares = [to_decimal(weight) for weight in weights]
    total = sum(shares, Decimal("0"))
    if total <= 0:
        raise ValueError("weights must sum to a positive number")
    return sum((value * weight for value, weight in zip(values, shares)), Decimal("0")) / total


def aggregate_carriers(
    cells: list[CellResult],
    weights: WeightSet,
    *,
    value_attr: str = "adjusted",
) -> list[RouteIndex]:
    groups: dict[tuple, list[CellResult]] = defaultdict(list)
    for cell in cells:
        value = getattr(cell, value_attr)
        if cell.suppressed or value is None:
            continue
        groups[(cell.period, cell.route, cell.apw_days)].append(cell)

    rows: list[RouteIndex] = []
    for (period, route, apw), group in sorted(groups.items()):
        carriers = [cell.carrier for cell in group]
        phi = weights.normalised_carriers(route, carriers)
        value = sum((phi[cell.carrier] * getattr(cell, value_attr) for cell in group), Decimal("0"))
        table = weights.carrier_weights.get(route, {})
        rows.append(
            RouteIndex(
                period=period,
                route=route,
                apw_days=apw,
                value=value,
                n_carriers=len(carriers),
                n_matched=sum(cell.n_matched for cell in group),
                carrier_weight_sum=sum((table.get(carrier, Decimal("0")) for carrier in carriers), Decimal("0")),
            )
        )
    return rows


def aggregate_routes(by_route: list[RouteIndex], weights: WeightSet) -> list[ApwIndex]:
    groups: dict[tuple, list[RouteIndex]] = defaultdict(list)
    for row in by_route:
        groups[(row.period, row.apw_days)].append(row)
    full = weights.basket_route_total()
    rows: list[ApwIndex] = []
    for (period, apw), group in sorted(groups.items()):
        routes = [item.route for item in group]
        share = weights.normalised_routes(routes)
        value = sum((share[item.route] * item.value for item in group), Decimal("0"))
        got = sum((weights.route_weights.get(item.route, Decimal("0")) for item in group), Decimal("0"))
        coverage = (Decimal("100") * got / full) if full > 0 else Decimal("0")
        rows.append(
            ApwIndex(
                period=period,
                apw_days=apw,
                value=value,
                n_routes=len(routes),
                n_matched=sum(item.n_matched for item in group),
                coverage_pct=coverage,
            )
        )
    return rows


def aggregate_apw(by_apw: list[ApwIndex], omega: dict[int, Decimal]) -> list[dict]:
    groups: dict[str, list[ApwIndex]] = defaultdict(list)
    for row in by_apw:
        groups[row.period].append(row)
    rows: list[dict] = []
    for period, group in sorted(groups.items()):
        present = [int(item.apw_days) for item in group]
        sub = {window: to_decimal(omega.get(window, 0)) for window in present}
        total = sum(sub.values(), Decimal("0"))
        if total <= 0:
            sub = {window: Decimal("1") / Decimal(len(present)) for window in present}
            total = Decimal("1")
        values = {item.apw_days: item.value for item in group}
        value = sum(((sub[window] / total) * values[window] for window in present), Decimal("0"))
        coverage = mean_decimal(item.coverage_pct for item in group)
        rows.append(
            {
                "period": period,
                "value": value,
                "n_apw": len(present),
                "n_matched": sum(item.n_matched for item in group),
                "coverage_pct": coverage,
                "omega_covered": total,
            }
        )
    return rows


def mean_decimal(values) -> Decimal:
    items = list(values)
    if not items:
        return Decimal("0")
    return sum(items, Decimal("0")) / Decimal(len(items))
