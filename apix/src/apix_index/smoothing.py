"""Day-of-week de-seasonalising (Part 4, section 1.1).

The confound: if tau is held fixed and t advances one day, the departure date
advances one day too -- so a Tuesday-departure observation becomes a
Wednesday-departure observation. Fares are strongly day-of-week dependent, so a
naive daily index reports pure day-of-week variation as inflation.

The fix: a 7-day CENTRED GEOMETRIC moving average of the daily cell relatives.
Centred and of length exactly 7, it annihilates a weekly cycle exactly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def centred_geometric_ma(series: pd.Series, window: int = 7) -> pd.Series:
    """7-day centred geometric moving average, computed in log space.

    Endpoints are handled with min_periods=1 so the series does not lose three
    days at each end; the reduced effective window at the edges is reported in
    the diagnostics rather than hidden.
    """
    if window <= 1:
        return series.astype(float)
    s = pd.Series(series, dtype=float).sort_index()
    positive = s.where(s > 0)
    logged = np.log(positive)
    smoothed = logged.rolling(window=window, center=True, min_periods=1).mean()
    return np.exp(smoothed)


def geometric_mean(values) -> float:
    """Geometric mean, used for the weekly and monthly rollups.

    Monthly aggregation uses the geometric mean of daily indices, consistent
    with MoSPI's own use of geometric means for annual averages in the
    linking-factor computation (Part 4, section 11).
    """
    v = np.asarray([x for x in np.asarray(values, dtype=float) if np.isfinite(x) and x > 0])
    if v.size == 0:
        return float("nan")
    return float(np.exp(np.mean(np.log(v))))
