"""Availability adjustment.

    I_adj = (I_matched)^A * (I_LAF)^(1-A)

A is the share of fare families still offered relative to the cell's reference
bundle, clamped to (0, 1]. At A = 1 the result equals the matched index.
"""

from __future__ import annotations

from decimal import Decimal

from apix_index.decimal_math import exp, ln, to_decimal

MIN_RATIO = Decimal("0.000001")


def availability_ratio(n_offered: Decimal | int | float, n_reference: Decimal | int | float) -> Decimal:
    reference = to_decimal(n_reference)
    if reference <= 0:
        return Decimal("1")
    ratio = to_decimal(n_offered) / reference
    if ratio > 1:
        return Decimal("1")
    if ratio <= 0:
        return MIN_RATIO
    return ratio


def blend(matched, laf, availability) -> Decimal | None:
    matched_value = None if matched is None else to_decimal(matched)
    laf_value = None if laf is None else to_decimal(laf)
    if matched_value is None or matched_value <= 0:
        return laf_value if laf_value is not None and laf_value > 0 else None
    if laf_value is None or laf_value <= 0:
        return matched_value
    ratio = to_decimal(availability)
    if ratio < 0:
        ratio = Decimal("0")
    if ratio > 1:
        ratio = Decimal("1")
    return exp(ratio * ln(matched_value) + (Decimal("1") - ratio) * ln(laf_value))


def compute_availability_adjustment(
    matched: Decimal,
    lowest_available: Decimal,
    availability_ratio: Decimal,
) -> Decimal:
    """Blend matched and lowest-available-fare indices by availability."""
    result = blend(matched, lowest_available, availability_ratio)
    if result is None:
        raise ValueError("availability adjustment requires a positive matched or LAF index")
    return result
