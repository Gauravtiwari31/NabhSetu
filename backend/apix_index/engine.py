"""Nabhsetu index engine: quotes + weights + method config -> published numbers."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

from apix_index.availability import availability_ratio, blend
from apix_index.coverage import cell_suppression
from apix_index.decimal_math import geometric_mean, ln, to_decimal
from apix_index.jevons import INDEX_SCALE, jevons_from_log_relatives
from apix_index.smoothing import centred_geometric_ma
from apix_index.types import (
    PUBLISHABLE,
    CellResult,
    HeadlinePoint,
    IndexResult,
    MethodConfig,
    Quote,
    WeightSet,
)
from apix_index.uncertainty import decimal_ci, flight_block_bootstrap
from apix_index.young import aggregate_apw, aggregate_carriers, aggregate_routes

REQUIRED = (
    "collected_date",
    "departure_date",
    "route",
    "carrier",
    "apw_days",
    "flight_number",
    "fare_family",
    "cabin",
    "stops",
    "price",
)


def _as_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def quote_from_mapping(row: Mapping[str, Any]) -> Quote:
    missing = [name for name in REQUIRED if name not in row]
    if missing:
        raise ValueError("quotes is missing required columns: " + repr(missing))
    return Quote(
        collected_date=_as_date(row["collected_date"]),
        departure_date=_as_date(row["departure_date"]),
        route=str(row["route"]),
        carrier=str(row["carrier"]),
        apw_days=int(row["apw_days"]),
        flight_number=str(row["flight_number"]),
        fare_family=str(row["fare_family"]),
        cabin=str(row["cabin"]),
        stops=int(row.get("stops") or 0),
        price=to_decimal(row["price"]),
        is_sold_out=bool(row.get("is_sold_out", False)),
        disposition=str(row.get("disposition", "ACCEPTED")),
        observation_id=None if row.get("observation_id") is None else str(row["observation_id"]),
    )


def _coerce_quotes(quotes: Iterable[Quote | Mapping[str, Any]]) -> list[Quote]:
    items: list[Quote] = []
    for row in quotes:
        items.append(row if isinstance(row, Quote) else quote_from_mapping(row))
    return items


def _prepare(quotes: Sequence[Quote | Mapping[str, Any]], config: MethodConfig) -> list[Quote]:
    prepared: list[Quote] = []
    for quote in _coerce_quotes(quotes):
        if quote.disposition not in PUBLISHABLE:
            continue
        if quote.price <= 0:
            continue
        prepared.append(quote)
    if not prepared:
        raise ValueError("no publishable quotes: nothing to index")

    grouped: dict[tuple, list[Quote]] = defaultdict(list)
    for quote in prepared:
        grouped[(quote.kappa(), quote.period_for(config.basis))].append(quote)

    collapsed: list[Quote] = []
    for (_kappa, _period), group in grouped.items():
        first = group[0]
        price = geometric_mean(item.price for item in group)
        assert price is not None
        collapsed.append(
            Quote(
                collected_date=first.collected_date,
                departure_date=first.departure_date,
                route=first.route,
                carrier=first.carrier,
                apw_days=first.apw_days,
                flight_number=first.flight_number,
                fare_family=first.fare_family,
                cabin=first.cabin,
                stops=first.stops,
                price=price,
                is_sold_out=any(item.is_sold_out for item in group),
                disposition=first.disposition,
                observation_id=first.observation_id,
                n_sources=len(group),
            )
        )
    return collapsed


def _cell_indices(quotes: list[Quote], config: MethodConfig) -> tuple[list[CellResult], dict]:
    periods = sorted({quote.period_for(config.basis) for quote in quotes})
    base = periods[0]
    by_period: dict[str, list[Quote]] = defaultdict(list)
    for quote in quotes:
        by_period[quote.period_for(config.basis)].append(quote)

    base_kappa = {quote.kappa(): quote.price for quote in by_period[base]}
    base_laf = {}
    for quote in by_period[base]:
        key = quote.flight_key()
        base_laf[key] = quote.price if key not in base_laf else min(base_laf[key], quote.price)

    family_counts: dict[tuple, set[str]] = defaultdict(set)
    for quote in quotes:
        family_counts[(quote.period_for(config.basis), quote.cell_key())].add(quote.fare_family)
    reference_families: dict[tuple, int] = defaultdict(int)
    for (_period, cell), families in family_counts.items():
        reference_families[cell] = max(reference_families[cell], len(families))

    cells: list[CellResult] = []
    blocks: dict[tuple, dict] = {}
    all_keys = {(period, quote.cell_key()) for period, group in by_period.items() for quote in group}

    for period, cell_key in sorted(all_keys):
        group = [quote for quote in by_period[period] if quote.cell_key() == cell_key]
        matched_relatives: list[Decimal] = []
        matched_by_flight: dict[str, list[Decimal]] = defaultdict(list)
        for quote in group:
            base_price = base_kappa.get(quote.kappa())
            if base_price is None:
                continue
            relative = ln(quote.price) - ln(base_price)
            matched_relatives.append(relative)
            matched_by_flight[quote.flight_number].append(relative)

        laf_relatives: list[Decimal] = []
        laf_by_flight: dict[str, Decimal] = {}
        current_laf: dict[tuple, Decimal] = {}
        for quote in group:
            key = quote.flight_key()
            current_laf[key] = quote.price if key not in current_laf else min(current_laf[key], quote.price)
        for flight_key, price in current_laf.items():
            base_price = base_laf.get(flight_key)
            if base_price is None:
                continue
            relative = ln(price) - ln(base_price)
            laf_relatives.append(relative)
            laf_by_flight[flight_key[3]] = relative

        matched = jevons_from_log_relatives(matched_relatives) if matched_relatives else None
        laf = jevons_from_log_relatives(laf_relatives) if laf_relatives else None
        n_families = len(family_counts[(period, cell_key)])
        availability = availability_ratio(n_families, reference_families[cell_key])
        if config.apply_availability_adjustment:
            adjusted = blend(matched, laf, availability)
        else:
            adjusted = matched
        n_matched = len(matched_relatives)
        cells.append(
            CellResult(
                period=period,
                route=cell_key[0],
                carrier=cell_key[1],
                apw_days=int(cell_key[2]),
                matched=matched,
                laf=laf,
                availability=availability,
                adjusted=adjusted,
                adjusted_raw=adjusted,
                n_matched=n_matched,
                n_quotes=len(group),
                n_families=n_families,
                suppressed=n_matched < config.n_min or adjusted is None,
            )
        )
        blocks[(period, cell_key[0], cell_key[1], int(cell_key[2]))] = {
            "matched": {flight: relatives for flight, relatives in matched_by_flight.items()},
            "laf": laf_by_flight,
            "availability": availability,
        }

    return cells, {"base_period": base, "blocks": blocks}


def _smooth_cells(cells: list[CellResult], config: MethodConfig) -> list[CellResult]:
    if not config.apply_dow_smoothing or config.dow_window <= 1:
        return cells
    grouped: dict[tuple, list[CellResult]] = defaultdict(list)
    for cell in cells:
        grouped[(cell.route, cell.carrier, cell.apw_days)].append(cell)
    smoothed: list[CellResult] = []
    for _key, group in grouped.items():
        group.sort(key=lambda item: item.period)
        series = [item.adjusted if item.adjusted is not None else Decimal("0") for item in group]
        values = centred_geometric_ma(series, config.dow_window)
        for cell, value in zip(group, values):
            cell.adjusted_raw = cell.adjusted
            if cell.adjusted is not None and value > 0:
                cell.adjusted = value
            smoothed.append(cell)
    return smoothed


def _effective_weights(
    cells: list[CellResult],
    weights: WeightSet,
    omega: dict[int, Decimal],
) -> dict[str, dict[tuple, Decimal]]:
    live = [cell for cell in cells if not cell.suppressed and cell.adjusted is not None]
    by_period: dict[str, list[CellResult]] = defaultdict(list)
    for cell in live:
        by_period[cell.period].append(cell)
    effective: dict[str, dict[tuple, Decimal]] = {}
    for period, group in by_period.items():
        windows = sorted({int(cell.apw_days) for cell in group})
        raw = {window: omega.get(window, Decimal("0")) for window in windows}
        total = sum(raw.values(), Decimal("0"))
        om = (
            {window: weight / total for window, weight in raw.items()}
            if total > 0
            else {window: Decimal("1") / Decimal(len(windows)) for window in windows}
        )
        table: dict[tuple, Decimal] = {}
        by_apw: dict[int, list[CellResult]] = defaultdict(list)
        for cell in group:
            by_apw[int(cell.apw_days)].append(cell)
        for apw, apw_group in by_apw.items():
            routes = sorted({cell.route for cell in apw_group})
            route_share = weights.normalised_routes(routes)
            by_route: dict[str, list[CellResult]] = defaultdict(list)
            for cell in apw_group:
                by_route[cell.route].append(cell)
            for route, route_group in by_route.items():
                carriers = sorted({cell.carrier for cell in route_group})
                phi = weights.normalised_carriers(route, carriers)
                for carrier in carriers:
                    table[(route, carrier, apw)] = om[apw] * route_share[route] * phi[carrier]
        effective[period] = table
    return effective


def _bootstrap_headline(blocks: dict, effective: dict, config: MethodConfig) -> dict[str, dict]:
    if config.bootstrap_draws <= 0:
        return {}
    rows: dict[str, dict] = {}
    ci_level = float(config.ci_level)
    for period, table in effective.items():
        flight_blocks: dict[str, list[float]] = {}
        for (route, carrier, apw), _weight in table.items():
            entry = blocks.get((period, route, carrier, apw), {})
            for flight, relatives in entry.get("matched", {}).items():
                flight_blocks[f"{route}:{carrier}:{apw}:{flight}"] = [float(item) for item in relatives]
        if not flight_blocks:
            continue

        def estimator(relatives: Sequence[float]) -> float:
            if not relatives:
                return float("nan")
            return float(jevons_from_log_relatives(relatives))

        _point, se, lo, hi = flight_block_bootstrap(
            flight_blocks,
            estimator,
            draws=config.bootstrap_draws,
            seed=config.bootstrap_seed,
            ci_level=ci_level,
        )
        rows[period] = {"se": se, "ci_low": lo, "ci_high": hi}
    return rows


def compute(quotes: Sequence[Quote | Mapping[str, Any]], weights: WeightSet, config: MethodConfig) -> IndexResult:
    prepared = _prepare(quotes, config)
    cells, extra = _cell_indices(prepared, config)
    base_period = extra["base_period"]
    cells = _smooth_cells(cells, config)
    omega = config.omega_vector()
    by_route = aggregate_carriers(cells, weights, value_attr="adjusted")
    by_apw = aggregate_routes(by_route, weights)
    headline_rows = aggregate_apw(by_apw, omega)
    raw_route = aggregate_carriers(cells, weights, value_attr="adjusted_raw")
    raw_head = {row["period"]: row["value"] for row in aggregate_apw(aggregate_routes(raw_route, weights), omega)}
    effective = _effective_weights(cells, weights, omega)
    intervals = _bootstrap_headline(extra["blocks"], effective, config)

    quotes_by_period: dict[str, int] = defaultdict(int)
    cells_by_period: dict[str, int] = defaultdict(int)
    for cell in cells:
        quotes_by_period[cell.period] += cell.n_quotes
        if not cell.suppressed:
            cells_by_period[cell.period] += 1

    headline: list[HeadlinePoint] = []
    for row in headline_rows:
        period = row["period"]
        value = row["value"]
        raw = raw_head.get(period)
        factor = (value / raw) if raw not in (None, 0) else Decimal("1")
        interval = intervals.get(period, {})
        se = decimal_ci(interval.get("se"))
        lo = decimal_ci(interval.get("ci_low"))
        hi = decimal_ci(interval.get("ci_high"))
        if se is not None:
            se = se * factor
        if lo is not None:
            lo = lo * factor
        if hi is not None:
            hi = hi * factor
        if lo is not None and hi is not None and lo > hi:
            lo, hi = hi, lo
        if lo is not None and value < lo:
            lo = value
        if hi is not None and value > hi:
            hi = value
        headline.append(
            HeadlinePoint(
                period=period,
                value=value,
                se=se,
                ci_low=lo,
                ci_high=hi,
                n_quotes=quotes_by_period.get(period, 0),
                n_cells=cells_by_period.get(period, 0),
                n_matched=row["n_matched"],
                n_apw=row["n_apw"],
                coverage_pct=row["coverage_pct"],
                omega_covered=row["omega_covered"],
                value_unsmoothed=raw,
            )
        )

    diagnostics = {
        "base_period": base_period,
        "n_periods": len(headline),
        **cell_suppression(cells),
        "mean_availability": round(
            float(sum((cell.availability for cell in cells), Decimal("0")) / Decimal(max(len(cells), 1))),
            4,
        ),
        "omega": {str(key): format(value, "f") for key, value in omega.items()},
        "n_min": config.n_min,
        "availability_adjustment": config.apply_availability_adjustment,
        "dow_smoothing": config.apply_dow_smoothing,
    }
    return IndexResult(
        headline=sorted(headline, key=lambda item: item.period),
        by_apw=sorted(by_apw, key=lambda item: (item.period, item.apw_days)),
        by_route=sorted(by_route, key=lambda item: (item.period, item.route, item.apw_days)),
        cells=sorted(cells, key=lambda item: (item.period, item.route, item.carrier, item.apw_days)),
        diagnostics=diagnostics,
        method_version=config.method_version,
        weights_version=weights.weights_version,
        basis=config.basis,
        variant=config.variant,
        omega_preset=config.omega_preset,
    )
