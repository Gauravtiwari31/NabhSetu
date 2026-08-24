"""Back-test: formal agreement statistics against an official comparator.

Part 7, USP 6. The point is that this is NOT an eyeballed chart overlay. It is
a set of named statistics with a benchmark, reported whether or not they
flatter the index.

    "How do you know your index is right?"
    "We don't KNOW; we bound it."

Never say accurate. Say bounded and reproducible. And include one unflattering
number on the evidence slide -- a back-test that reports only wins is not a
back-test.

WHAT IS BEING COMPARED, HONESTLY
--------------------------------
The CPI extracts loaded so far stop at the Transport aggregate; there is no
air-fare item index in them. Transport also contains road fuel, vehicle
purchase, rail fares and communication, all of which move for reasons entirely
unrelated to airfares -- and air fare is a small slice of it. So agreement is
DILUTED BY CONSTRUCTION, and a weak correlation here is the expected result,
not evidence that APIx is broken. The comparator level is stamped on every
result row so nobody can quote a number without knowing what it compared.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    if x.size < 3 or np.std(x) == 0 or np.std(y) == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    if x.size < 3:
        return float("nan")
    rx = pd.Series(x).rank().values
    ry = pd.Series(y).rank().values
    return _pearson(rx, ry)


def bland_altman(a: np.ndarray, b: np.ndarray) -> Dict[str, float]:
    """Agreement between two measurements of the same quantity.

    Reports the mean difference (bias) and the limits of agreement, which is
    the right tool here: correlation answers "do they move together", but
    Bland-Altman answers "by how much do they disagree", which is what a
    statistical office actually wants to know.
    """
    diff = a - b
    mean_diff = float(np.mean(diff))
    sd = float(np.std(diff, ddof=1)) if diff.size > 1 else float("nan")
    return {
        "bias": mean_diff,
        "sd_diff": sd,
        "loa_low": mean_diff - 1.96 * sd,
        "loa_high": mean_diff + 1.96 * sd,
        "mean_abs_diff": float(np.mean(np.abs(diff))),
    }


def directional_agreement(a: np.ndarray, b: np.ndarray) -> Dict[str, float]:
    """Share of periods where both series moved the same way.

    Often the statistic a policy user cares about most: not the level, but
    whether the indicator called the turn.
    """
    da, dbb = np.diff(a), np.diff(b)
    if da.size == 0:
        return {"directional_agreement_pct": float("nan"), "n_moves": 0}
    both = np.sign(da) == np.sign(dbb)
    return {"directional_agreement_pct": float(100.0 * both.mean()), "n_moves": int(da.size)}


def rmse_vs_random_walk(target: np.ndarray, predictor: np.ndarray) -> Dict[str, float]:
    """Does the predictor beat a naive random walk on the target?

    The benchmark exists so that a positive result means something. If APIx does
    not beat a random walk, we say so: a negative result honestly reported is
    more credible than an unvalidated claim.
    """
    if target.size < 4:
        return {"rmse_model": float("nan"), "rmse_random_walk": float("nan"),
                "skill_vs_rw_pct": float("nan")}
    # Random walk: next value = current value.
    rw_err = np.diff(target)
    rmse_rw = float(np.sqrt(np.mean(rw_err ** 2)))

    # Predictor scaled onto the target by OLS, so the comparison is about
    # information content rather than units.
    X = np.column_stack([np.ones(predictor.size), predictor])
    beta, *_ = np.linalg.lstsq(X, target, rcond=None)
    fitted = X @ beta
    rmse_model = float(np.sqrt(np.mean((target - fitted) ** 2)))
    skill = float(100.0 * (1.0 - rmse_model / rmse_rw)) if rmse_rw > 0 else float("nan")
    return {"rmse_model": rmse_model, "rmse_random_walk": rmse_rw, "skill_vs_rw_pct": skill}


def lead_lag(a: np.ndarray, b: np.ndarray, max_lag: int = 6) -> List[Dict[str, float]]:
    """Cross-correlation at a range of leads and lags.

    A positive best-lag means APIx moves FIRST, which is the leading-indicator
    claim. It has to be demonstrated, not asserted.
    """
    out = []
    n = a.size
    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            x, y = a[:n + lag], b[-lag:]
        elif lag > 0:
            x, y = a[lag:], b[:n - lag]
        else:
            x, y = a, b
        if x.size >= 3:
            out.append({"lag_months": lag, "corr": _pearson(x, y), "n": int(x.size)})
    return out


def run(conn: sqlite3.Connection, apix: pd.DataFrame, comparator: pd.DataFrame,
        apix_code: str = "APIx-T", apix_basis: str = "travel",
        comparator_name: str = "CPI-2024 Transport (All India, Combined)",
        comparator_level: str = "division",
        is_synthetic: bool = False, run_id: Optional[str] = None,
        persist: bool = True) -> Dict[str, object]:
    """Align two monthly series and compute every agreement statistic.

    `apix` needs columns (period, value); `comparator` needs (period, idx).
    Both are aligned on calendar-month start, inner join -- only months where
    BOTH exist are used, and the count is reported.
    """
    run_id = run_id or f"backtest-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    a = apix.copy()
    a["period"] = pd.to_datetime(a["period"]).dt.to_period("M").dt.to_timestamp()
    a = a.groupby("period", as_index=False)["value"].mean()

    c = comparator.copy()
    c["period"] = pd.to_datetime(c["period"]).dt.to_period("M").dt.to_timestamp()
    c = c.groupby("period", as_index=False)["idx"].mean()

    m = a.merge(c, on="period", how="inner").sort_values("period").dropna()
    n = len(m)

    result: Dict[str, object] = {
        "run_id": run_id,
        "apix_code": apix_code, "apix_basis": apix_basis,
        "comparator": comparator_name, "comparator_level": comparator_level,
        "n_overlapping_months": n,
        "apix_range": [str(a.period.min().date()), str(a.period.max().date())] if len(a) else None,
        "comparator_range": [str(c.period.min().date()), str(c.period.max().date())] if len(c) else None,
        "is_synthetic": bool(is_synthetic),
        "statistics": {},
        "caveats": [],
    }

    if comparator_level != "item":
        result["caveats"].append(
            "Comparator is the Transport aggregate, not the air fare item. Transport "
            "also contains road fuel, vehicle purchase, rail fares and communication, "
            "and air fare is a small slice of it, so agreement is diluted by "
            "construction. A weak correlation here is expected and is NOT evidence "
            "that APIx is wrong.")
    if is_synthetic:
        result["caveats"].append(
            "APIx side is SYNTHETIC. These statistics describe the simulator's "
            "relationship to real CPI, which is not a meaningful quantity. They "
            "verify that the harness computes, nothing more. Do not present them "
            "as validation.")

    # The hard floor. Below this nothing is reportable, and saying so is the
    # correct output -- not a number with a wide interval nobody reads.
    MIN_MONTHS = 6
    if n < MIN_MONTHS:
        result["statistics"] = {}
        result["caveats"].append(
            f"Only {n} overlapping month(s); at least {MIN_MONTHS} are needed before "
            f"any agreement statistic is reportable. Nothing computed.")
        result["reportable"] = False
        if persist:
            _persist(conn, result, [])
        return result

    result["reportable"] = True
    x = m["value"].to_numpy(float)
    y = m["idx"].to_numpy(float)

    stats: Dict[str, float] = {
        "pearson_r_level": _pearson(x, y),
        "spearman_rho_level": _spearman(x, y),
    }

    # Month-on-month log changes: the comparison that actually matters for an
    # index, since two trending series correlate on level almost regardless.
    if n >= 4:
        dx = np.diff(np.log(x))
        dy = np.diff(np.log(y))
        stats["pearson_r_mom_change"] = _pearson(dx, dy)
        stats["spearman_rho_mom_change"] = _spearman(dx, dy)

    # Rebase both to their first overlapping month so Bland-Altman compares
    # like with like; the two series have different base periods otherwise.
    xr = 100.0 * x / x[0]
    yr = 100.0 * y / y[0]
    stats.update({f"bland_altman_{k}": v for k, v in bland_altman(xr, yr).items()})
    stats.update(directional_agreement(x, y))
    stats.update(rmse_vs_random_walk(y, x))

    result["statistics"] = stats
    result["lead_lag"] = lead_lag(x, y, max_lag=min(6, max(1, n // 3)))
    best = max((d for d in result["lead_lag"] if np.isfinite(d["corr"])),
               key=lambda d: abs(d["corr"]), default=None)
    result["best_lag"] = best
    aligned = m.assign(period=m["period"].dt.strftime("%Y-%m-%d"))
    aligned = aligned.replace([np.inf, -np.inf], np.nan)
    result["aligned"] = [
        {k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in r.items()}
        for r in aligned.astype(object).where(aligned.notna(), None).to_dict("records")]

    if persist:
        _persist(conn, result, list(stats.items()))
    return result


def _persist(conn: sqlite3.Connection, result: Dict[str, object], stats) -> None:
    now = datetime.now(timezone.utc).isoformat()
    rows = [(result["run_id"], now, result["apix_code"], result["apix_basis"],
             result["comparator"], "monthly", int(result["n_overlapping_months"]),
             name, (None if value is None or not np.isfinite(value) else float(value)),
             result["comparator_level"], int(bool(result["is_synthetic"])))
            for name, value in stats]
    if rows:
        conn.executemany(
            "INSERT INTO fact_backtest_result "
            "(run_id, computed_at, apix_code, apix_basis, comparator, frequency, "
            " n_periods, statistic, value, detail, is_synthetic) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
