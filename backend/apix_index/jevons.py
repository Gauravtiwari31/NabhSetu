"""Jevons elementary index and contrast formulae (Dutot, Carli).

Jevons is the geometric mean of matched price relatives, scaled to 100:

    I_t = 100 * exp( (1/n) * Σ ln(p_t,i / p_0,i) )
"""

from __future__ import annotations

from decimal import Decimal

from apix_index.decimal_math import ensure_positive, exp, ln, mean, to_decimal

INDEX_SCALE = Decimal("100")


def _paired(current_prices, base_prices) -> tuple[list[Decimal], list[Decimal]]:
    current = [to_decimal(value) for value in current_prices]
    base = [to_decimal(value) for value in base_prices]
    if len(current) != len(base):
        raise ValueError(f"matched vectors must be the same length, got {len(current)} and {len(base)}")
    if not current:
        raise ValueError("cannot compute an index from an empty matched sample")
    for price in current + base:
        ensure_positive(price, "prices")
    return current, base


def log_relatives(base_prices, current_prices) -> list[Decimal]:
    current, base = _paired(current_prices, base_prices)
    return [ln(pt) - ln(p0) for pt, p0 in zip(current, base)]


def compute_jevons(current_prices: list, base_prices: list) -> Decimal:
    """Return the Jevons elementary index (base = 100)."""
    return jevons(base_prices, current_prices)


def jevons(base_prices, current_prices) -> Decimal:
    relatives = log_relatives(base_prices, current_prices)
    return INDEX_SCALE * exp(mean(relatives))


def jevons_from_log_relatives(relatives) -> Decimal:
    values = [to_decimal(item) for item in relatives]
    if not values:
        raise ValueError("cannot compute an index from an empty matched sample")
    return INDEX_SCALE * exp(mean(values))


def dutot(base_prices, current_prices) -> Decimal:
    current, base = _paired(current_prices, base_prices)
    return INDEX_SCALE * (mean(current) / mean(base))


def carli(base_prices, current_prices) -> Decimal:
    current, base = _paired(current_prices, base_prices)
    relatives = [pt / p0 for pt, p0 in zip(current, base)]
    return INDEX_SCALE * mean(relatives)


def jevons_se(relatives) -> Decimal | None:
    values = [to_decimal(item) for item in relatives]
    n = len(values)
    if n < 2:
        return None
    index = jevons_from_log_relatives(values)
    centre = mean(values)
    variance = sum((item - centre) ** 2 for item in values) / Decimal(n - 1)
    stdev = variance.sqrt()
    return index * stdev / Decimal(n).sqrt()


def jevons_se_float(relatives) -> float:
    value = jevons_se(relatives)
    return float("nan") if value is None else float(value)
