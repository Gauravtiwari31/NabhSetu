"""Coverage and confidence metadata for a published index run."""

from __future__ import annotations

from decimal import Decimal

from apix_index.types import CellResult, WeightSet


def route_coverage_pct(present_routes: list[str], weights: WeightSet) -> Decimal:
    full = weights.basket_route_total()
    if full <= 0:
        return Decimal("0")
    got = sum((weights.route_weights.get(route, Decimal("0")) for route in present_routes), Decimal("0"))
    return Decimal("100") * got / full


def cell_suppression(cells: list[CellResult]) -> dict:
    total = len(cells)
    suppressed = sum(1 for cell in cells if cell.suppressed)
    return {
        "n_cells_total": total,
        "n_cells_suppressed": suppressed,
        "suppression_pct": round(float(Decimal("100") * Decimal(suppressed) / Decimal(max(total, 1))), 2),
    }
