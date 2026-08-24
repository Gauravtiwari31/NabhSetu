"""The lead-time elasticity surface (Part 4, section 9).

Pooled log-linear regression with fixed effects:

    ln p_i = a + b1*ln(tau) + b2*ln(tau)^2 + gamma_r + lambda_c
             + theta_dow(d) + psi_month(d) + rho*Holiday + eps

Standard errors are CLUSTERED BY FLIGHT, because quotes on the same flight
across fare families and collection days are strongly dependent and classical
OLS errors would be far too small.

The lead-time elasticity of fare is

    eta(tau) = d ln p / d ln tau = b1 + 2*b2*ln(tau)

Because b2 enters, the elasticity VARIES WITH LEAD TIME -- which matters, since
fares typically fall from tau=45 to a trough somewhere around tau=21-30 and then
rise sharply approaching departure. The trough is at

    tau* = exp( -b1 / (2*b2) )

which is the single most press-friendly output of the whole system: "the
cheapest time to book DEL-BOM is tau* days out."

Implemented in NumPy rather than statsmodels so the package carries no heavy
dependency and the arithmetic is auditable line by line.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd


@dataclass
class ElasticityFit:
    coefficients: Dict[str, float]
    std_errors: Dict[str, float]
    beta1: float
    beta2: float
    se_beta1: float
    se_beta2: float
    tau_star: Optional[float]
    tau_star_ci: Optional[tuple]
    r_squared: float
    adj_r_squared: float
    n_obs: int
    n_clusters: int
    n_params: int
    note: str = ""

    def eta(self, tau) -> np.ndarray:
        """eta(tau) = b1 + 2*b2*ln(tau)."""
        t = np.asarray(tau, dtype=float)
        return self.beta1 + 2.0 * self.beta2 * np.log(np.maximum(t, 1e-9))

    def eta_se(self, tau, cov: Optional[np.ndarray] = None) -> np.ndarray:
        """Delta-method SE of eta(tau) from the 2x2 block of the covariance."""
        t = np.asarray(tau, dtype=float)
        if cov is None:
            return np.full(t.shape, np.nan)
        g1 = np.ones_like(t)
        g2 = 2.0 * np.log(np.maximum(t, 1e-9))
        var = (g1 ** 2) * cov[0, 0] + (g2 ** 2) * cov[1, 1] + 2 * g1 * g2 * cov[0, 1]
        return np.sqrt(np.maximum(var, 0.0))


def _dummies(values: pd.Series, prefix: str, drop_first: bool = True):
    cats = sorted(values.dropna().unique())
    if drop_first:
        cats = cats[1:]
    cols, names = [], []
    for c in cats:
        cols.append((values == c).astype(float).values)
        names.append(f"{prefix}[{c}]")
    return (np.column_stack(cols) if cols else np.empty((len(values), 0))), names


def fit(quotes: pd.DataFrame, price_col: str = "price_T",
        holidays: Optional[Sequence[str]] = None,
        route: Optional[str] = None,
        with_route_fe: bool = True, with_carrier_fe: bool = True) -> ElasticityFit:
    """Fit the surface. Pass `route` to get a per-route tau*."""
    df = quotes.copy()
    if route:
        df = df[df["route"] == route]
        with_route_fe = False

    price = pd.to_numeric(df[price_col], errors="coerce")
    df = df[price.notna() & (price > 0) & df["apw_days"].notna()]
    if len(df) < 30:
        raise ValueError(f"too few observations to fit ({len(df)}); need at least 30")

    y = np.log(pd.to_numeric(df[price_col], errors="coerce").values)
    ltau = np.log(np.maximum(df["apw_days"].astype(float).values, 1.0))

    dep = pd.to_datetime(df["departure_date"])
    blocks: List[np.ndarray] = [np.ones((len(df), 1)), ltau.reshape(-1, 1), (ltau ** 2).reshape(-1, 1)]
    names: List[str] = ["const", "ln_tau", "ln_tau_sq"]

    if with_route_fe and df["route"].nunique() > 1:
        m, n = _dummies(df["route"], "route")
        blocks.append(m); names += n
    if with_carrier_fe and df["carrier"].nunique() > 1:
        m, n = _dummies(df["carrier"], "carrier")
        blocks.append(m); names += n

    dow = dep.dt.dayofweek.astype(str)
    if dow.nunique() > 1:
        m, n = _dummies(dow, "dow")
        blocks.append(m); names += n

    month = dep.dt.month.astype(str)
    if month.nunique() > 1:
        m, n = _dummies(month, "month")
        blocks.append(m); names += n

    if holidays:
        hol = dep.dt.strftime("%Y-%m-%d").isin(set(holidays)).astype(float).values
        if hol.std() > 0:
            blocks.append(hol.reshape(-1, 1)); names.append("holiday")

    X = np.column_stack(blocks)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    n, k = X.shape

    ss_res = float(resid @ resid)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    adj = 1.0 - (1.0 - r2) * (n - 1) / max(n - k, 1)

    # Cluster-robust covariance, clustered on flight.
    XtX_inv = np.linalg.pinv(X.T @ X)
    cluster_key = (df["route"].astype(str) + "|" + df["carrier"].astype(str) + "|"
                   + df["flight_number"].astype(str)).values
    uniq = pd.unique(cluster_key)
    meat = np.zeros((k, k))
    for c in uniq:
        idx = cluster_key == c
        Xc, uc = X[idx], resid[idx]
        s = Xc.T @ uc
        meat += np.outer(s, s)
    g = len(uniq)
    scale = (g / max(g - 1, 1)) * ((n - 1) / max(n - k, 1)) if g > 1 else 1.0
    cov = scale * (XtX_inv @ meat @ XtX_inv)
    se = np.sqrt(np.maximum(np.diag(cov), 0.0))

    b1, b2 = float(beta[1]), float(beta[2])
    tau_star, tau_ci, note = None, None, ""
    if b2 > 1e-9:
        tau_star = float(np.exp(-b1 / (2.0 * b2)))
        # Delta-method CI on ln(tau*) = -b1/(2*b2), then exponentiated.
        d1 = -1.0 / (2.0 * b2)
        d2 = b1 / (2.0 * b2 ** 2)
        var_ln = (d1 ** 2) * cov[1, 1] + (d2 ** 2) * cov[2, 2] + 2 * d1 * d2 * cov[1, 2]
        if var_ln > 0:
            half = 1.96 * np.sqrt(var_ln)
            tau_ci = (float(np.exp(-b1 / (2 * b2) - half)), float(np.exp(-b1 / (2 * b2) + half)))
        if not (1.0 <= tau_star <= 365.0):
            note = (f"tau* = {tau_star:.1f} lies outside the observed window set; "
                    "the quadratic is extrapolating and the number should not be published")
            tau_star = None
    else:
        note = ("b2 <= 0: the fitted fare-vs-lead-time curve has no interior minimum "
                "over the observed windows, so tau* is not identified. Reporting this "
                "is correct; inventing a trough is not.")

    return ElasticityFit(
        coefficients=dict(zip(names, map(float, beta))),
        std_errors=dict(zip(names, map(float, se))),
        beta1=b1, beta2=b2, se_beta1=float(se[1]), se_beta2=float(se[2]),
        tau_star=tau_star, tau_star_ci=tau_ci,
        r_squared=float(r2), adj_r_squared=float(adj),
        n_obs=int(n), n_clusters=int(g), n_params=int(k), note=note,
    )


def surface(fit_result: ElasticityFit, taus: Sequence[int], cov: Optional[np.ndarray] = None
            ) -> pd.DataFrame:
    """eta(tau) with its band, ready to chart."""
    t = np.asarray(list(taus), dtype=float)
    eta = fit_result.eta(t)
    se = fit_result.eta_se(t, cov)
    return pd.DataFrame({"apw_days": t.astype(int), "eta": eta, "eta_se": se,
                         "eta_low": eta - 1.96 * se, "eta_high": eta + 1.96 * se})


def fare_ladder(quotes: pd.DataFrame, route: str, carrier: str,
                price_col: str = "price_T", max_components: int = 6) -> Dict[str, object]:
    """Recover the airline's fare ladder with a 1-D Gaussian mixture in log space.

    Because airlines price from discrete RBDs the empirical fare distribution
    within a route-carrier is MULTI-MODAL. The fitted means are estimates of the
    bucket structure, recovered from public prices with no privileged data.

    Tracking the means over time separates "the airline raised its fare ladder"
    (structural) from "more people bought so we are selling from a higher
    bucket" (compositional). J is chosen by BIC.
    """
    from sklearn.mixture import GaussianMixture

    sub = quotes[(quotes["route"] == route) & (quotes["carrier"] == carrier)]
    price = pd.to_numeric(sub[price_col], errors="coerce")
    y = np.log(price[price > 0].dropna().values).reshape(-1, 1)
    if len(y) < 50:
        return {"route": route, "carrier": carrier, "n_obs": int(len(y)),
                "error": "too few observations to fit a mixture (need 50+)"}

    best, best_bic, bics = None, np.inf, {}
    for j in range(1, max_components + 1):
        gm = GaussianMixture(n_components=j, random_state=0, n_init=3).fit(y)
        bic = float(gm.bic(y))
        bics[j] = bic
        if bic < best_bic:
            best, best_bic = gm, bic

    order = np.argsort(best.means_.ravel())
    return {
        "route": route, "carrier": carrier, "n_obs": int(len(y)),
        "n_components": int(best.n_components), "bic": best_bic, "bic_by_j": bics,
        "buckets": [
            {"rank": i + 1,
             "fare_inr": float(np.exp(best.means_.ravel()[k])),
             "sd_log": float(np.sqrt(best.covariances_.ravel()[k])),
             "weight": float(best.weights_.ravel()[k])}
            for i, k in enumerate(order)],
    }
