"""Decimal helpers for reproducible index arithmetic."""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Iterable

DEFAULT_PREC = 34
QUANTIZE_PUBLISHED = Decimal("0.000001")
ZERO = Decimal("0")
ONE = Decimal("1")


def to_decimal(value: Decimal | int | float | str | None) -> Decimal:
    if value is None:
        raise ValueError("missing numeric value")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def ln(value: Decimal) -> Decimal:
    if value <= 0:
        raise ValueError("logarithm is defined only for positive numbers")
    with localcontext() as ctx:
        ctx.prec = DEFAULT_PREC
        return value.ln()


def exp(value: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = DEFAULT_PREC
        return value.exp()


def mean(values: Iterable[Decimal]) -> Decimal:
    items = list(values)
    if not items:
        raise ValueError("cannot average an empty sample")
    return sum(items, ZERO) / Decimal(len(items))


def geometric_mean(values: Iterable[Decimal | int | float | str]) -> Decimal | None:
    positives = [to_decimal(item) for item in values if item is not None and to_decimal(item) > 0]
    if not positives:
        return None
    return exp(mean(ln(item) for item in positives))


def quantize_index(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(QUANTIZE_PUBLISHED)


def ensure_positive(value: Decimal, label: str = "price") -> Decimal:
    if value <= 0:
        raise ValueError(f"{label} must be strictly positive")
    return value
