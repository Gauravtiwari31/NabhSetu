"""Availability adjustment (Part 4, section 8).

The bias this fixes, stated plainly: a cell normally offers fare families at
Rs 4,000 / 6,000 / 9,000. During a demand surge the two cheap buckets sell out.
A strictly matched index observes only the Rs 9,000 quote -- which has not
CHANGED price -- so it reports ZERO inflation during the exact episode a
consumer experiences as a fare explosion.

This is the single most defensible methodological criticism of a naive
matched-model fare index, and fixing it is APIx's best ninety seconds of demo.
"""
from __future__ import annotations

import numpy as np


def availability_ratio(n_offered: float, n_reference: float) -> float:
    """A_g(t) = # fare families offered at t / # in the cell's reference bundle.

    Clamped to (0, 1]. A value above 1 (more families offered than in the
    reference bundle) is clamped down rather than allowed to invert the blend
    exponent -- the blend is only defined as an interpolation.
    """
    if n_reference <= 0:
        return 1.0
    a = float(n_offered) / float(n_reference)
    if not np.isfinite(a):
        return 1.0
    return float(min(max(a, 1e-6), 1.0))


def blend(matched: float, laf: float, a: float) -> float:
    """Availability-Adjusted APIx: a geometric blend controlled by A.

        I_adj = (I_matched)^A * (I_LAF)^(1-A)

    Properties that make this defensible rather than ad hoc:
      * A = 1 (everything available) -> reduces EXACTLY to the matched index,
        so nothing changes in the normal case;
      * A -> 0 (buckets closing) -> converges to the lowest-available-fare
        index, which does capture the surge;
      * continuous and monotone in A throughout.
    """
    if matched is None or not np.isfinite(matched) or matched <= 0:
        return float(laf) if laf is not None and np.isfinite(laf) and laf > 0 else float("nan")
    if laf is None or not np.isfinite(laf) or laf <= 0:
        return float(matched)
    a = float(min(max(a, 0.0), 1.0))
    return float(np.exp(a * np.log(matched) + (1.0 - a) * np.log(laf)))
