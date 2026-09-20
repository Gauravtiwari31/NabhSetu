"""Checksum-preserving DGCA public-file import.

Official fare/yield tables are never fabricated. A missing or incompatible
file yields an empty result and provenance of the attempt.
"""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.database.models.publication import ReferenceObservation
from app.reference_data.checksum import sha256_file


PERIOD_FIELDS = ("period", "month", "date", "year_month")
ROUTE_FIELDS = ("route", "sector", "city_pair")
VALUE_FIELDS = ("fare", "yield", "avg_fare", "average_fare", "value", "index")
METRIC_FIELDS = ("metric", "series", "indicator")


def _cell(row: dict, names: tuple[str, ...]) -> str | None:
    lowered = {key.lower().strip(): value for key, value in row.items()}
    for name in names:
        if name in lowered and lowered[name] not in (None, ""):
            return str(lowered[name]).strip()
    return None


def _parse_period(raw: str) -> date | None:
    text = raw.strip()
    for size in (10, 7):
        candidate = text[:size]
        try:
            if len(candidate) == 7:
                return date.fromisoformat(candidate + "-01")
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _parse_decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", "").replace("₹", "").strip())
    except (InvalidOperation, AttributeError, ValueError):
        return None


def load_dgca_file(
    path: Path,
    *,
    source_url: str | None = None,
    metric_default: str = "average_fare",
) -> list[ReferenceObservation]:
    checksum = sha256_file(path)
    rows: list[ReferenceObservation] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return rows
        for raw in reader:
            period_raw = _cell(raw, PERIOD_FIELDS)
            value_raw = _cell(raw, VALUE_FIELDS)
            if not period_raw or not value_raw:
                continue
            period = _parse_period(period_raw)
            value = _parse_decimal(value_raw)
            if period is None or value is None:
                continue
            rows.append(
                ReferenceObservation(
                    dataset="dgca",
                    period=period,
                    route=_cell(raw, ROUTE_FIELDS),
                    metric=_cell(raw, METRIC_FIELDS) or metric_default,
                    value=value,
                    unit="INR" if "fare" in (metric_default or "") else None,
                    source_url=source_url,
                    file_name=path.name,
                    checksum=checksum,
                    raw_row_json=dict(raw),
                )
            )
    return rows
