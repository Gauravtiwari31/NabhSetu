"""Honest validation against official DGCA/CPI files.

This module never fabricates official series. If a compatible comparator or
enough overlapping monthly observations is missing, the result is
`unavailable` or `not_reportable`.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from app.database.models.publication import BacktestResult, PublishedIndexValue, ReferenceObservation
from app.domain.enums import BacktestStatus, IndexFrequency
from app.domain.models import utcnow

MIN_OVERLAP = 3
COMPATIBLE_METRICS = {
    "dgca": {"average_fare", "fare", "yield", "avg_fare", "passengers", "traffic"},
    "cpi": {"cpi_air_fare", "cpi", "air_fare", "airfare", "index"},
}


def _month(value) -> str:
    return value.isoformat()[:7]


def _pearson(xs: list[Decimal], ys: list[Decimal]) -> Decimal | None:
    if len(xs) < MIN_OVERLAP:
        return None
    mx = sum(xs, Decimal("0")) / Decimal(len(xs))
    my = sum(ys, Decimal("0")) / Decimal(len(ys))
    num = sum(((x - mx) * (y - my) for x, y in zip(xs, ys)), Decimal("0"))
    denx = sum(((x - mx) ** 2 for x in xs), Decimal("0")).sqrt()
    deny = sum(((y - my) ** 2 for y in ys), Decimal("0")).sqrt()
    if denx == 0 or deny == 0:
        return None
    return num / (denx * deny)


def _mape(xs: list[Decimal], ys: list[Decimal]) -> Decimal | None:
    if not xs:
        return None
    total = Decimal("0")
    count = 0
    for left, right in zip(xs, ys):
        if right == 0:
            continue
        total += abs(left - right) / abs(right)
        count += 1
    if count == 0:
        return None
    return Decimal("100") * total / Decimal(count)


def compare_monthly(
    published: list[PublishedIndexValue],
    reference: list[ReferenceObservation],
    *,
    comparator: str,
    run_id=None,
) -> BacktestResult:
    monthly = [row for row in published if row.frequency == IndexFrequency.MONTHLY and row.series == "headline"]
    compatible = [
        row
        for row in reference
        if row.dataset == comparator and row.metric in COMPATIBLE_METRICS.get(comparator, set()) and row.value is not None
    ]
    if not compatible:
        return BacktestResult(
            run_id=run_id,
            comparator=comparator,
            status=BacktestStatus.UNAVAILABLE,
            notes="No compatible official file rows were imported for this comparator.",
            details_json={"reason": "missing_comparator"},
            computed_at=utcnow(),
        )
    if not monthly:
        return BacktestResult(
            run_id=run_id,
            comparator=comparator,
            status=BacktestStatus.NOT_REPORTABLE,
            notes="Monthly APIx values are not available for an official comparison.",
            details_json={"reason": "missing_monthly_apix"},
            computed_at=utcnow(),
        )

    official: dict[str, list[Decimal]] = defaultdict(list)
    for row in compatible:
        official[_month(row.period)].append(row.value)
    official_mean = {period: sum(values, Decimal("0")) / Decimal(len(values)) for period, values in official.items()}
    pairs: list[tuple[str, Decimal, Decimal]] = []
    for row in monthly:
        key = _month(row.period)
        if key in official_mean:
            pairs.append((key, row.value, official_mean[key]))
    overlap = len(pairs)
    if overlap < MIN_OVERLAP:
        return BacktestResult(
            run_id=run_id,
            comparator=comparator,
            status=BacktestStatus.NOT_REPORTABLE,
            overlap_months=overlap,
            notes=(
                f"Only {overlap} overlapping month(s). A correlation is not reported "
                f"below {MIN_OVERLAP} months of compatible observations."
            ),
            details_json={"reason": "insufficient_overlap", "months": [item[0] for item in pairs]},
            computed_at=utcnow(),
        )

    xs = [item[1] for item in pairs]
    ys = [item[2] for item in pairs]
    correlation = _pearson(xs, ys)
    mape = _mape(xs, ys)
    return BacktestResult(
        run_id=run_id,
        comparator=comparator,
        status=BacktestStatus.REPORTABLE,
        correlation=correlation,
        mape=mape,
        overlap_months=overlap,
        notes="Comparison uses imported public-file values only.",
        details_json={
            "months": [item[0] for item in pairs],
            "apix": [format(item[1], "f") for item in pairs],
            "official": [format(item[2], "f") for item in pairs],
        },
        computed_at=utcnow(),
    )
