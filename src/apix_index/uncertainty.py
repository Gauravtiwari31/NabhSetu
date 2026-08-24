"""Uncertainty: delta-method standard errors and the flight-block bootstrap.

The line to hold in the Q&A (Part 8, section 5, Q.4): we do not KNOW the index
is right, we BOUND it. Never say "accurate"; say "bounded and reproducible".

Blocking on FLIGHT rather than on quote is the methodological point. Quotes on
the same flight across fare families and lead-time windows are strongly
dependent; an i.i.d. bootstrap over quotes would understate the interval, which
is exactly the failure mode a statistician judge will look for.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Sequence, Tuple

import numpy as np


def flight_block_bootstrap(
    blocks: Dict[str, np.ndarray],
    estimator: Callable[[np.ndarray], float],
    draws: int = 500,
    seed: int = 20260822,
    ci_level: float = 0.90,
) -> Tuple[float, float, float, float]:
    """Resample whole flights with replacement; recompute; take percentiles.

    `blocks` maps a flight id to that flight's vector of log price relatives.
    Returns (point_estimate, se, ci_low, ci_high). Deterministic given `seed`,
    which is what makes `make reproduce` print zero differences.
    """
    keys: List[str] = sorted(blocks.keys())
    if not keys:
        return (float("nan"),) * 4
    pooled = np.concatenate([np.asarray(blocks[k], dtype=float) for k in keys])
    if pooled.size == 0:
        return (float("nan"),) * 4
    point = float(estimator(pooled))
    if len(keys) < 2 or draws <= 0:
        return point, float("nan"), float("nan"), float("nan")

    rng = np.random.default_rng(seed)
    n = len(keys)
    stats = np.empty(draws, dtype=float)
    arrays = [np.asarray(blocks[k], dtype=float) for k in keys]
    for d in range(draws):
        pick = rng.integers(0, n, size=n)
        sample = np.concatenate([arrays[i] for i in pick])
        stats[d] = estimator(sample) if sample.size else np.nan

    stats = stats[np.isfinite(stats)]
    if stats.size < 2:
        return point, float("nan"), float("nan"), float("nan")
    alpha = (1.0 - ci_level) / 2.0
    lo, hi = np.percentile(stats, [100 * alpha, 100 * (1 - alpha)])
    return point, float(stats.std(ddof=1)), float(lo), float(hi)


def delta_method_se(log_relatives: Sequence[float]) -> float:
    """SE of a Jevons index by the delta method: SE = I * s / sqrt(n)."""
    lr = np.asarray(list(log_relatives), dtype=float)
    lr = lr[np.isfinite(lr)]
    if lr.size < 2:
        return float("nan")
    idx = 100.0 * float(np.exp(lr.mean()))
    return float(idx * lr.std(ddof=1) / np.sqrt(lr.size))
