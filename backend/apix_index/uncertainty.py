"""Uncertainty: delta-method standard errors and a flight-block bootstrap."""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal

from apix_index.decimal_math import to_decimal
from apix_index.jevons import jevons_from_log_relatives, jevons_se


def delta_method_se(log_relatives: Sequence) -> float:
    value = jevons_se(log_relatives)
    return float("nan") if value is None else float(value)


def _percentile(sorted_values: list[float], probability: float) -> float:
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[int(position)]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def flight_block_bootstrap(
    blocks: Mapping[str, Sequence[float]],
    estimator: Callable[[Sequence[float]], float],
    draws: int = 500,
    seed: int = 20260822,
    ci_level: float = 0.90,
) -> tuple[float, float, float, float]:
    keys = sorted(blocks)
    if not keys:
        return (float("nan"),) * 4
    pooled: list[float] = []
    arrays = []
    for key in keys:
        array = [float(item) for item in blocks[key]]
        arrays.append(array)
        pooled.extend(array)
    if not pooled:
        return (float("nan"),) * 4
    point = float(estimator(pooled))
    if len(keys) < 2 or draws <= 0:
        return point, float("nan"), float("nan"), float("nan")

    rng = random.Random(seed)
    n = len(keys)
    stats: list[float] = []
    for _ in range(draws):
        sample: list[float] = []
        for _pick in range(n):
            sample.extend(arrays[rng.randrange(n)])
        if sample:
            stats.append(float(estimator(sample)))
    finite = [item for item in stats if math.isfinite(item)]
    if len(finite) < 2:
        return point, float("nan"), float("nan"), float("nan")
    finite.sort()
    alpha = (1.0 - ci_level) / 2.0
    se = math.sqrt(sum((item - sum(finite) / len(finite)) ** 2 for item in finite) / (len(finite) - 1))
    return point, se, _percentile(finite, alpha), _percentile(finite, 1.0 - alpha)


def decimal_ci(value: float | None) -> Decimal | None:
    if value is None or not math.isfinite(value):
        return None
    return to_decimal(value)
