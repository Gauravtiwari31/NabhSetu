"""Checksum-preserving CPI air-fare import from a downloaded public file."""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.database.models.publication import ReferenceObservation
from app.reference_data.checksum import sha256_file

PERIOD_FIELDS = ("period", "month", "date", "year_month")
VALUE_FIELDS = ("cpi", "air_fare", "airfare", "index", "value")


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


def load_cpi_file(path: Path, *, source_url: str | None = None) -> list[ReferenceObservation]:
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
            try:
                value = Decimal(value_raw.replace(",", "").strip())
            except (InvalidOperation, AttributeError, ValueError):
                continue
            if period is None:
                continue
            rows.append(
                ReferenceObservation(
                    dataset="cpi",
                    period=period,
                    route=None,
                    metric="cpi_air_fare",
                    value=value,
                    unit="index",
                    source_url=source_url,
                    file_name=path.name,
                    checksum=checksum,
                    raw_row_json=dict(raw),
                )
            )
    return rows
