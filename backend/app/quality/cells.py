from __future__ import annotations

from decimal import Decimal

from app.domain.enums import AvailabilityState, PublicationDisposition, ValidationDisposition
from app.domain.models import CanonicalFareObservation, ValidationFlag


def tukey_fences(values: list[Decimal], k: Decimal = Decimal("3")) -> tuple[Decimal, Decimal] | None:
    if len(values) < 4:
        return None
    ordered = sorted(values)
    q1 = _percentile(ordered, Decimal("0.25"))
    q3 = _percentile(ordered, Decimal("0.75"))
    iqr = q3 - q1
    return q1 - k * iqr, q3 + k * iqr


def hampel_bounds(values: list[Decimal], z: Decimal = Decimal("3.5")) -> tuple[Decimal, Decimal] | None:
    if len(values) < 3:
        return None
    ordered = sorted(values)
    median = _percentile(ordered, Decimal("0.5"))
    deviations = sorted(abs(value - median) for value in ordered)
    mad = _percentile(deviations, Decimal("0.5"))
    scale = Decimal("1.4826") * mad
    if scale == 0:
        return median, median
    return median - z * scale, median + z * scale


def _percentile(ordered: list[Decimal], probability: Decimal) -> Decimal:
    if len(ordered) == 1:
        return ordered[0]
    position = probability * Decimal(len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - Decimal(lower)
    return ordered[lower] * (Decimal("1") - weight) + ordered[upper] * weight


def winsorise(value: Decimal, lower: Decimal, upper: Decimal) -> Decimal:
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


def cell_outlier_flags(prices: list[Decimal], observation: CanonicalFareObservation, *, tukey_k: Decimal, hampel_z: Decimal) -> list[ValidationFlag]:
    flags: list[ValidationFlag] = []
    tukey = tukey_fences(prices, tukey_k)
    if tukey is not None:
        lower, upper = tukey
        if observation.total_fare < lower or observation.total_fare > upper:
            flags.append(
                ValidationFlag(
                    code="TUKEY_OUTLIER",
                    message="fare sits outside the cell Tukey fences",
                    disposition=ValidationDisposition.FLAGGED,
                    details={"lower": format(lower, "f"), "upper": format(upper, "f")},
                )
            )
    hampel = hampel_bounds(prices, hampel_z)
    if hampel is not None:
        lower, upper = hampel
        if observation.total_fare < lower or observation.total_fare > upper:
            flags.append(
                ValidationFlag(
                    code="HAMPEL_OUTLIER",
                    message="fare sits outside the cell Hampel bounds",
                    disposition=ValidationDisposition.FLAGGED,
                    details={"lower": format(lower, "f"), "upper": format(upper, "f")},
                )
            )
    return flags
