"""The CPI Transport nowcast bridge (Part 4, section 10).

APIx is daily. The CPI is monthly, published around the 12th of the following
month. That gap is the forecasting opportunity, and this is the ONE genuinely
fitted (trained) model in the whole system -- everything else is deterministic
index arithmetic.

    pi_m = alpha + sum_j beta_j x_{m-j} + sum_k rho_k pi_{m-k} + delta ATF_m + u_m

where pi_m is monthly CPI transport inflation and x_m is the monthly average of
the APIx travel-basis series.

WHAT THIS MODULE REFUSES TO DO
------------------------------
It will not report interpretable coefficients when the fit cannot support them.
Two guards, both of which return a refusal rather than a number:

  1. TOO FEW OBSERVATIONS. A bridge with lags and an ATF control needs far more
     than a handful of months. Fitting k parameters on n ~ k observations
     produces an R^2 near 1 and coefficients that mean nothing. The module
     requires a minimum ratio of observations to parameters.

  2. SYNTHETIC INPUT. Regressing real CPI on a simulator output estimates the
     relationship between real inflation and a random number generator. The
     arithmetic succeeds; the coefficient is meaningless. Results are returned
     stamped `interpretable: False` with the reason attached.

Both guards exist because the failure mode here is not a crash -- it is a
plausible-looking table of coefficients that nobody can defend under
questioning. Part 8: "never fabricate", and "a negative result honestly
reported is more credible than an unvalidated claim."

Out-of-sample evaluation is EXPANDING-WINDOW, never a random split: a random
train/test split on a time series leaks the future into the past and is the
single most common way a nowcast is accidentally overstated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

# A fit needs at least this many observations per estimated parameter before
# its coefficients are treated as interpretable.
MIN_OBS_PER_PARAM = 8
MIN_OBS_ABSOLUTE = 24


@dataclass
class NowcastFit:
    coefficients: Dict[str, float]
    std_errors: Dict[str, float]
    t_stats: Dict[str, float]
    n_obs: int
    n_params: int
    r_squared: float
    adj_r_squared: float
    interpretable: bool
    reasons: List[str] = field(default_factory=list)
    in_sample_rmse: float = float("nan")
    oos: Dict[str, float] = field(default_factory=dict)
    spec: Dict[str, object] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [f"n={self.n_obs}  params={self.n_params}  "
                 f"R2={self.r_squared:.4f} adj={self.adj_r_squared:.4f}",
                 f"interpretable: {self.interpretable}"]
        for r in self.reasons:
            lines.append(f"  ! {r}")
        for k in self.coefficients:
            lines.append(f"  {k:<20s} {self.coefficients[k]:+.5f}  "
                         f"(se {self.std_errors[k]:.5f}, t {self.t_stats[k]:+.2f})")
        return "\n".join(lines)


def build_design(apix_monthly: pd.DataFrame, cpi: pd.DataFrame,
                 apix_lags: Sequence[int] = (0, 1),
                 cpi_lags: Sequence[int] = (1,),
                 atf: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Assemble the bridge design matrix on a monthly calendar.

    `apix_monthly`: (period, value). `cpi`: (period, idx). `atf`: (period, price).
    The CPI target is y-o-y log inflation, computed from the index when the
    published `inflation` column is absent or incomplete.
    """
    a = apix_monthly.copy()
    a["period"] = pd.to_datetime(a["period"]).dt.to_period("M").dt.to_timestamp()
    a = a.groupby("period", as_index=False)["value"].mean().rename(columns={"value": "apix"})

    c = cpi.copy()
    c["period"] = pd.to_datetime(c["period"]).dt.to_period("M").dt.to_timestamp()
    c = c.groupby("period", as_index=False)["idx"].mean().sort_values("period")
    # y-o-y log inflation, in percent
    c["cpi_infl"] = 100.0 * (np.log(c["idx"]) - np.log(c["idx"].shift(12)))

    df = c.merge(a, on="period", how="left").sort_values("period").reset_index(drop=True)
    df["apix_growth"] = 100.0 * (np.log(df["apix"]) - np.log(df["apix"].shift(1)))

    for j in apix_lags:
        df[f"apix_g_l{j}"] = df["apix_growth"].shift(j)
    for k in cpi_lags:
        df[f"cpi_infl_l{k}"] = df["cpi_infl"].shift(k)

    if atf is not None and len(atf):
        t = atf.copy()
        t["period"] = pd.to_datetime(t["period"]).dt.to_period("M").dt.to_timestamp()
        t = t.groupby("period", as_index=False)["price"].mean()
        df = df.merge(t, on="period", how="left")
        df["atf_growth"] = 100.0 * (np.log(df["price"]) - np.log(df["price"].shift(1)))

    return df


def _ols(X: np.ndarray, y: np.ndarray):
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    n, k = X.shape
    dof = max(n - k, 1)
    sigma2 = float(resid @ resid) / dof
    XtX_inv = np.linalg.pinv(X.T @ X)
    se = np.sqrt(np.maximum(np.diag(sigma2 * XtX_inv), 0.0))
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float(resid @ resid) / ss_tot if ss_tot > 0 else float("nan")
    adj = 1.0 - (1.0 - r2) * (n - 1) / dof if np.isfinite(r2) else float("nan")
    return beta, se, r2, adj, resid


def fit(design: pd.DataFrame, regressors: Optional[Sequence[str]] = None,
        is_synthetic: bool = False, min_oos: int = 6) -> NowcastFit:
    """Fit the bridge, with the two honesty guards applied to the result."""
    if regressors is None:
        regressors = [c for c in design.columns
                      if c.startswith(("apix_g_l", "cpi_infl_l", "atf_growth"))]
    regressors = list(regressors)

    cols = ["cpi_infl"] + regressors
    d = design[cols].replace([np.inf, -np.inf], np.nan).dropna()
    n = len(d)
    k = len(regressors) + 1

    reasons: List[str] = []
    if n == 0:
        return NowcastFit({}, {}, {}, 0, k, float("nan"), float("nan"), False,
                          ["no overlapping observations after lagging and differencing; "
                           "nothing to fit"], spec={"regressors": regressors})

    y = d["cpi_infl"].to_numpy(float)
    X = np.column_stack([np.ones(n)] + [d[r].to_numpy(float) for r in regressors])
    beta, se, r2, adj, resid = _ols(X, y)
    names = ["const"] + regressors

    interpretable = True
    if n < MIN_OBS_ABSOLUTE:
        interpretable = False
        reasons.append(
            f"only {n} usable observations (need >= {MIN_OBS_ABSOLUTE}). The CPI 2024 "
            f"series begins in 2025 and y-o-y inflation costs a further 12 months, so a "
            f"defensible bridge is not estimable from it yet. Coefficients are NOT "
            f"reportable.")
    if n < MIN_OBS_PER_PARAM * k:
        interpretable = False
        reasons.append(
            f"{n} observations for {k} parameters (< {MIN_OBS_PER_PARAM} per parameter). "
            f"R^2 here is an artefact of the parameter count, not fit quality.")
    if is_synthetic:
        interpretable = False
        reasons.append(
            "the APIx regressor is SYNTHETIC. This estimates the relationship between "
            "real CPI inflation and a simulator, which is not a meaningful quantity. "
            "The fit verifies the harness computes; it validates nothing.")

    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(se > 0, beta / se, np.nan)

    out = NowcastFit(
        coefficients=dict(zip(names, map(float, beta))),
        std_errors=dict(zip(names, map(float, se))),
        t_stats=dict(zip(names, map(float, t))),
        n_obs=n, n_params=k, r_squared=float(r2), adj_r_squared=float(adj),
        interpretable=interpretable, reasons=reasons,
        in_sample_rmse=float(np.sqrt(np.mean(resid ** 2))),
        spec={"regressors": regressors, "target": "cpi_infl (y-o-y log %)"},
    )
    out.oos = expanding_window_oos(d, regressors, min_train=max(12, k + 2), min_oos=min_oos)
    return out


def expanding_window_oos(d: pd.DataFrame, regressors: Sequence[str],
                         min_train: int = 12, min_oos: int = 6) -> Dict[str, float]:
    """Out-of-sample RMSE against a no-change benchmark, expanding window.

    Never a random split. At each step the model sees only the past, predicts
    one month ahead, and is scored against the naive "inflation stays where it
    was" forecast -- which is a genuinely hard benchmark for monthly inflation.
    """
    n = len(d)
    if n < min_train + min_oos:
        return {"n_oos": 0,
                "note": f"need {min_train + min_oos} observations for an expanding-window "
                        f"evaluation, have {n}; no out-of-sample result"}

    y = d["cpi_infl"].to_numpy(float)
    X = np.column_stack([np.ones(n)] + [d[r].to_numpy(float) for r in regressors])

    preds, actuals, naive = [], [], []
    for t in range(min_train, n):
        beta, *_ = np.linalg.lstsq(X[:t], y[:t], rcond=None)
        preds.append(float(X[t] @ beta))
        actuals.append(float(y[t]))
        naive.append(float(y[t - 1]))          # no-change benchmark

    preds, actuals, naive = map(np.array, (preds, actuals, naive))
    rmse_model = float(np.sqrt(np.mean((actuals - preds) ** 2)))
    rmse_naive = float(np.sqrt(np.mean((actuals - naive) ** 2)))
    return {
        "n_oos": int(preds.size),
        "rmse_model": rmse_model,
        "rmse_no_change_benchmark": rmse_naive,
        "skill_vs_benchmark_pct": float(100.0 * (1.0 - rmse_model / rmse_naive))
        if rmse_naive > 0 else float("nan"),
        "beats_benchmark": bool(rmse_model < rmse_naive),
    }


def granger_causality(design: pd.DataFrame, cause: str = "apix_g_l1",
                      target: str = "cpi_infl", lags: int = 2) -> Dict[str, object]:
    """Does APIx help predict CPI beyond CPI's own history? An F-test.

    Reported with the same honesty guard: on a short sample the test has almost
    no power, so a non-rejection means "we cannot tell", never "no relationship".
    """
    d = design[[target, cause]].replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)
    frame = pd.DataFrame({"y": d[target]})
    for L in range(1, lags + 1):
        frame[f"y_l{L}"] = d[target].shift(L)
        frame[f"x_l{L}"] = d[cause].shift(L)
    frame = frame.dropna()
    n = len(frame)
    if n < 4 * (2 * lags + 1):
        return {"testable": False, "n": n,
                "note": f"only {n} observations for {2*lags+1} parameters; the test has "
                        f"effectively no power. Non-rejection would mean 'cannot tell', "
                        f"not 'no relationship'."}

    y = frame["y"].to_numpy(float)
    restricted = np.column_stack([np.ones(n)] + [frame[f"y_l{L}"].to_numpy(float)
                                                 for L in range(1, lags + 1)])
    unrestricted = np.column_stack([restricted] + [frame[f"x_l{L}"].to_numpy(float)
                                                   for L in range(1, lags + 1)])
    _, _, _, _, r_res = _ols(restricted, y)
    _, _, _, _, r_unr = _ols(unrestricted, y)
    rss_r, rss_u = float(r_res @ r_res), float(r_unr @ r_unr)
    df1, df2 = lags, n - unrestricted.shape[1]
    if df2 <= 0 or rss_u <= 0:
        return {"testable": False, "n": n, "note": "degrees of freedom exhausted"}
    f = ((rss_r - rss_u) / df1) / (rss_u / df2)
    try:
        from scipy import stats as st
        p = float(1.0 - st.f.cdf(f, df1, df2))
    except Exception:
        p = float("nan")
    return {"testable": True, "n": n, "lags": lags, "f_stat": float(f),
            "df": [df1, df2], "p_value": p,
            "interpretation": ("APIx Granger-causes CPI transport inflation at 5%"
                               if np.isfinite(p) and p < 0.05 else
                               "cannot reject the null that APIx adds no predictive content")}
