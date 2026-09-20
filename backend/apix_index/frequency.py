"""Daily / weekly / monthly rollups of a published series."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from apix_index.decimal_math import geometric_mean, to_decimal
from apix_index.types import Frequency, HeadlinePoint


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def month_start(day: date) -> date:
    return day.replace(day=1)


def period_key(day: date, frequency: Frequency) -> date:
    if frequency == "daily":
        return day
    if frequency == "weekly":
        return week_start(day)
    if frequency == "monthly":
        return month_start(day)
    raise ValueError(f"unknown frequency {frequency!r}")


def to_frequency(points: list[HeadlinePoint], frequency: Frequency) -> list[HeadlinePoint]:
    if frequency == "daily":
        return list(points)
    buckets: dict[date, list[HeadlinePoint]] = defaultdict(list)
    for point in points:
        buckets[period_key(date.fromisoformat(point.period), frequency)].append(point)
    rolled: list[HeadlinePoint] = []
    for key, group in sorted(buckets.items()):
        values = [item.value for item in group if item.value > 0]
        geo = geometric_mean(values)
        if geo is None:
            continue
        coverage = sum((item.coverage_pct for item in group), Decimal("0")) / Decimal(len(group))
        se_values = [item.se for item in group if item.se is not None]
        rolled.append(
            HeadlinePoint(
                period=key.isoformat(),
                value=geo,
                se=(sum(se_values, Decimal("0")) / Decimal(len(se_values))) if se_values else None,
                ci_low=None,
                ci_high=None,
                n_quotes=sum(item.n_quotes for item in group),
                n_cells=sum(item.n_cells for item in group),
                n_matched=sum(item.n_matched for item in group),
                n_apw=max(item.n_apw for item in group),
                coverage_pct=coverage,
                omega_covered=max((item.omega_covered for item in group), default=Decimal("0")),
            )
        )
    return rolled


def decimal_or_none(value) -> Decimal | None:
    if value is None:
        return None
    return to_decimal(value)
