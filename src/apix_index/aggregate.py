"""Stages 2-4: carrier, route and lead-time aggregation.

Each stage is a weighted arithmetic mean of the stage below it, which is the
Young / Modified-Laspeyres form MoSPI uses above the elementary level. Keeping
the stages as separate pure functions is what lets a statistician review the
aggregation without reading the collection code.
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from .types import WeightSet


def aggregate_carriers(cells: pd.DataFrame, weights: WeightSet, value_col: str = "adjusted") -> pd.DataFrame:
    """Stage 2: I_{r,tau,t} = sum_c phi_{c|r} I_{(r,c,tau),t}.

    Only unsuppressed cells participate. The weight of a suppressed cell is
    redistributed pro-rata across the surviving carriers on the same route --
    which is exactly what `WeightSet.normalised_carriers` does.
    """
    live = cells[(~cells["suppressed"]) & cells[value_col].notna()]
    rows = []
    for (period, route, apw), grp in live.groupby(["period", "route", "apw_days"], sort=True):
        carriers = list(grp["carrier"])
        phi = weights.normalised_carriers(route, carriers)
        vals = grp.set_index("carrier")[value_col]
        value = float(sum(phi[c] * float(vals[c]) for c in carriers))
        rows.append({
            "period": period, "route": route, "apw_days": int(apw), "value": value,
            "n_carriers": len(carriers),
            "n_matched": int(grp["n_matched"].sum()),
            "carrier_weight_sum": float(sum(weights.carrier_weights.get(route, {}).get(c, 0.0) for c in carriers)),
        })
    return pd.DataFrame(rows, columns=[
        "period", "route", "apw_days", "value", "n_carriers", "n_matched", "carrier_weight_sum"])


def aggregate_routes(by_route: pd.DataFrame, weights: WeightSet) -> pd.DataFrame:
    """Stage 3: I_{tau,t} = sum_r w_r I_{r,tau,t}.

    w_r comes from DGCA/AAI sector traffic, or -- when PSD supplies its own
    route list and weights -- straight from the signed input file. The engine
    never derives w_r itself.
    """
    rows = []
    for (period, apw), grp in by_route.groupby(["period", "apw_days"], sort=True):
        routes = list(grp["route"])
        w = weights.normalised_routes(routes)
        vals = grp.set_index("route")["value"]
        value = float(sum(w[r] * float(vals[r]) for r in routes))
        # Coverage is reported as the share of the FULL basket weight that the
        # surviving routes account for -- an honest coverage ledger, not a
        # renormalised 100%.
        full = sum(weights.route_weights.values())
        got = sum(weights.route_weights.get(r, 0.0) for r in routes)
        rows.append({
            "period": period, "apw_days": int(apw), "value": value,
            "n_routes": len(routes),
            "n_matched": int(grp["n_matched"].sum()),
            "coverage_pct": float(100.0 * got / full) if full > 0 else float("nan"),
        })
    return pd.DataFrame(rows, columns=["period", "apw_days", "value", "n_routes", "n_matched", "coverage_pct"])


def aggregate_apw(by_apw: pd.DataFrame, omega: Dict[int, float]) -> pd.DataFrame:
    """Stage 4: APIx_t = sum_tau omega_tau I_{tau,t}.

    omega is a DECLARED POLICY PARAMETER, not a measurement. Windows absent
    from a given period are dropped and omega renormalised over what is
    present, so a missing window does not silently deflate the headline.
    """
    rows = []
    for period, grp in by_apw.groupby("period", sort=True):
        present = [int(a) for a in grp["apw_days"]]
        sub = {a: float(omega.get(a, 0.0)) for a in present}
        total = sum(sub.values())
        if total <= 0:
            sub = {a: 1.0 / len(present) for a in present}
            total = 1.0
        vals = grp.set_index("apw_days")["value"]
        value = float(sum((sub[a] / total) * float(vals[a]) for a in present))
        rows.append({
            "period": period, "value": value,
            "n_apw": len(present),
            "n_matched": int(grp["n_matched"].sum()),
            "coverage_pct": float(grp["coverage_pct"].mean()),
            "omega_covered": float(total),
        })
    return pd.DataFrame(rows, columns=["period", "value", "n_apw", "n_matched", "coverage_pct", "omega_covered"])


def to_frequency(daily: pd.DataFrame, frequency: str, value_col: str = "value") -> pd.DataFrame:
    """Weekly = 7-day geometric mean; monthly = calendar-month geometric mean.

    Geometric, not arithmetic, for consistency with MoSPI's own use of
    geometric means in the linking-factor computation (Part 4, section 11).
    """
    if frequency == "daily":
        return daily.copy()
    df = daily.copy()
    df["period"] = pd.to_datetime(df["period"])
    if frequency == "weekly":
        key = df["period"].dt.to_period("W").dt.start_time
    elif frequency == "monthly":
        key = df["period"].dt.to_period("M").dt.to_timestamp()
    else:
        raise ValueError(f"unknown frequency {frequency!r}")
    df["_k"] = key
    agg = df.groupby("_k").agg(
        value=(value_col, lambda s: float(np.exp(np.log(s[s > 0]).mean())) if (s > 0).any() else np.nan),
        n_matched=("n_matched", "sum") if "n_matched" in df.columns else (value_col, "size"),
        n_days=(value_col, "size"),
    ).reset_index().rename(columns={"_k": "period"})
    if "coverage_pct" in df.columns:
        cov = df.groupby("_k")["coverage_pct"].mean().reset_index().rename(columns={"_k": "period"})
        agg = agg.merge(cov, on="period", how="left")
    agg["period"] = agg["period"].dt.strftime("%Y-%m-%d")
    return agg
