"""Stage 1: elementary aggregate formulae.

Jevons is the APIx elementary formula because (a) MoSPI uses it for CPI 2024
(FAQ Q.20), (b) it satisfies time reversal and transitivity, and (c) fares are
approximately lognormal so the geometric mean is the natural centre.

Dutot and Carli are implemented for the three-formula comparison slide and for
the property tests that assert the AM-GM ordering.
"""
from __future__ import annotations

import numpy as np


def _as_array(x) -> np.ndarray:
    a = np.asarray(x, dtype=float)
    if a.ndim != 1:
        raise ValueError("price vectors must be one-dimensional")
    return a


def _validate_pair(p0: np.ndarray, pt: np.ndarray) -> None:
    if p0.shape != pt.shape:
        raise ValueError(f"matched vectors must be the same length, got {p0.shape} and {pt.shape}")
    if p0.size == 0:
        raise ValueError("cannot compute an index from an empty matched sample")
    if np.any(p0 <= 0) or np.any(pt <= 0):
        raise ValueError("prices must be strictly positive")


def jevons(p0, pt) -> float:
    """Geometric mean of price relatives, x100.

        I = 100 * exp( (1/n) * sum_i ln(p_it / p_i0) )

    Satisfies time reversal exactly: jevons(a,b) * jevons(b,a) == 100^2 / 100.
    """
    p0, pt = _as_array(p0), _as_array(pt)
    _validate_pair(p0, pt)
    return 100.0 * float(np.exp(np.mean(np.log(pt) - np.log(p0))))


def dutot(p0, pt) -> float:
    """Ratio of arithmetic means, x100. Unit-sensitive; shown for contrast."""
    p0, pt = _as_array(p0), _as_array(pt)
    _validate_pair(p0, pt)
    return 100.0 * float(np.mean(pt) / np.mean(p0))


def carli(p0, pt) -> float:
    """Arithmetic mean of price relatives, x100. Fails time reversal (upward bias)."""
    p0, pt = _as_array(p0), _as_array(pt)
    _validate_pair(p0, pt)
    return 100.0 * float(np.mean(pt / p0))


def log_relatives(p0, pt) -> np.ndarray:
    """The per-product log price relatives underlying a Jevons index."""
    p0, pt = _as_array(p0), _as_array(pt)
    _validate_pair(p0, pt)
    return np.log(pt) - np.log(p0)


def jevons_from_log_relatives(lr: np.ndarray) -> float:
    """Jevons given precomputed log relatives. Used by the bootstrap hot path."""
    lr = np.asarray(lr, dtype=float)
    if lr.size == 0:
        raise ValueError("cannot compute an index from an empty matched sample")
    return 100.0 * float(np.exp(lr.mean()))


def jevons_se(lr: np.ndarray) -> float:
    """Delta-method standard error of a Jevons index.

    With I = 100*exp(mean(lr)), dI/d(mean) = I, so
        SE(I) = I * SE(mean(lr)) = I * s / sqrt(n)
    where s is the sample standard deviation of the log relatives.
    """
    lr = np.asarray(lr, dtype=float)
    n = lr.size
    if n < 2:
        return float("nan")
    idx = jevons_from_log_relatives(lr)
    return float(idx * lr.std(ddof=1) / np.sqrt(n))
