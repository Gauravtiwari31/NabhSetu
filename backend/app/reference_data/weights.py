"""Traffic-derived route/carrier weights. Never invented from fare quotes."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from apix_index.types import WeightSet
from app.database.models.publication import ReferenceObservation


def weights_from_traffic(rows: list[ReferenceObservation], *, version: str) -> WeightSet | None:
    passengers = [row for row in rows if row.metric in {"passengers", "traffic", "pax"} and row.value and row.route]
    if not passengers:
        return None
    route_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    carrier_totals: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: Decimal("0")))
    for row in passengers:
        route_totals[row.route] += row.value
        carrier = (row.raw_row_json or {}).get("carrier") or (row.raw_row_json or {}).get("airline")
        if carrier:
            carrier_totals[row.route][str(carrier)] += row.value
    if not route_totals:
        return None
    carriers = {
        route: dict(table) if table else {"UN": Decimal("1")}
        for route, table in carrier_totals.items()
    }
    for route in route_totals:
        carriers.setdefault(route, {"UN": Decimal("1")})
    return WeightSet.from_mapping(route_totals, carriers, weights_version=version, source="dgca_traffic")
