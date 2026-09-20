"""Day-of-week de-seasonalising via a centred geometric moving average."""

from __future__ import annotations

from decimal import Decimal

from apix_index.decimal_math import geometric_mean, to_decimal


def centred_geometric_ma(series, window: int = 7) -> list[Decimal]:
    values = [to_decimal(item) for item in series]
    if window <= 1:
        return values
    half = window // 2
    smoothed: list[Decimal] = []
    for index, value in enumerate(values):
        lo = max(0, index - half)
        hi = min(len(values), index + half + 1)
        window_values = [item for item in values[lo:hi] if item > 0]
        smoothed.append(geometric_mean(window_values) if window_values else value)
    return smoothed
