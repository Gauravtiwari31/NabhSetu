"""Index run: quotes -> quality gate -> index engine -> fact_index_value.

This is the only place that joins the impure world (a database) to the pure
index engine. The engine itself never sees a connection.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from apix_index import MethodConfig, WeightSet, compute, to_frequency
from apix_pipeline.quality import blocking_failures, run_contract, summarise
from apix_store import db
from apix_store.errors import OperatorError


class PublicationBlocked(OperatorError):
    """Raised when a BLOCK-severity quality check fails. Nothing is published."""


def attach_variant_prices(quotes: pd.DataFrame) -> pd.DataFrame:
    """Rebuild the three variant price columns from the stored components.

    Uses `total_fare_capped` where the cleaner set it (disposition WINSORISED)
    and the observed `total_fare` otherwise. Reading `total_fare` unconditionally
    discards the cap, which let a quote marked WINSORISED enter the index at its
    full uncapped value -- the disposition label claiming a treatment that had
    not actually been applied to the number.

    The administered components (UDF, ASF, RCS) are fixed amounts and GST is ad
    valorem, so when the total is capped the base fare is re-derived as the
    residual at the same GST rate rather than scaled naively.
    """
    out = quotes.copy()
    num = lambda c: (pd.to_numeric(out[c], errors="coerce").fillna(0.0)  # noqa: E731
                     if c in out.columns else pd.Series(0.0, index=out.index))
    observed = pd.to_numeric(out["total_fare"], errors="coerce")
    capped = (pd.to_numeric(out["total_fare_capped"], errors="coerce")
              if "total_fare_capped" in out.columns else pd.Series(np.nan, index=out.index))
    effective = capped.where(capped.notna(), observed)
    out["total_fare_effective"] = effective

    base = num("base_fare")
    with np.errstate(divide="ignore", invalid="ignore"):
        gst_rate = (num("gst") / base.where(base > 0)).fillna(0.0)
    statutory = num("udf") + num("asf") + num("rcs_levy") + num("convenience_fee")
    base_effective = ((effective - statutory) / (1.0 + gst_rate)).where(
        capped.notna(), base)

    out["price_B"] = base_effective + num("yq_yr")        # pure airline pricing
    out["price_T"] = effective - num("convenience_fee")   # HEADLINE
    out["price_A"] = effective                            # all-in checkout cost
    return out


def _index_id(index_code: str, period: str, frequency: str, basis: str,
              omega_preset: str, method_version: str, weights_version: str) -> str:
    """Deterministic id, so a re-run with identical inputs produces identical ids."""
    raw = "|".join([index_code, period, frequency, basis, omega_preset,
                    method_version, weights_version])
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "apix:" + raw))


def run(conn: sqlite3.Connection, cfg: Dict, weights: WeightSet,
        variants: Optional[Sequence[str]] = None,
        bases: Sequence[str] = ("book", "travel"),
        presets: Optional[Sequence[str]] = None,
        run_id: Optional[str] = None,
        enforce_quality: bool = True,
        bootstrap_draws: Optional[int] = None,
        write_detail: bool = True) -> Dict[str, object]:
    """Compute and persist the full index family."""
    method = cfg["method"]
    variants = list(variants or method["variants"])
    presets = list(presets or method["omega_presets"].keys())
    run_id = run_id or f"index-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    quotes = db.read_quotes(conn, publishable_only=False)
    if quotes.empty:
        raise PublicationBlocked("no quotes in the store; collect before indexing")
    quotes = attach_variant_prices(quotes)

    expected_routes = [r[0] for r in conn.execute("SELECT route FROM dim_route")]
    checks = run_contract(quotes, conn=conn, expected_routes=expected_routes)
    db.record_quality(conn, run_id, checks)
    blockers = blocking_failures(checks)
    if blockers and enforce_quality:
        names = ", ".join(b["check_name"] for b in blockers)
        raise PublicationBlocked(f"publication blocked by quality contract: {names}")

    publishable = quotes[quotes["disposition"].isin(["ACCEPTED", "WINSORISED"])]
    is_synthetic = int(bool(publishable["is_synthetic"].fillna(0).astype(int).max()))

    now = datetime.now(timezone.utc).isoformat()
    rows: List[dict] = []
    results: Dict[str, object] = {}
    suppressed_headline: Dict[str, int] = {}
    headline_variant = method.get("headline_variant", "T")
    default_preset = method.get("default_omega_preset", "uniform")

    for variant in variants:
        frame = publishable.rename(columns={f"price_{variant}": "price"})
        frame = frame[frame["price"].notna() & (frame["price"] > 0)]
        for basis in bases:
            for preset in presets:
                omega = {int(k): float(v) for k, v in method["omega_presets"][preset].items()}
                # The flight-block bootstrap is the expensive step, and running
                # it for all 18 variant x basis x preset combinations buys
                # nothing: the sensitivity across presets is itself the
                # published uncertainty story for omega. Intervals are computed
                # for the HEADLINE configuration; the rest carry point
                # estimates, and the API says so rather than showing an empty
                # band as if it were a narrow one.
                is_headline_cfg = (variant == headline_variant and preset == default_preset)
                draws = int(method["bootstrap_draws"] if bootstrap_draws is None
                            else bootstrap_draws)
                mc = MethodConfig(
                    method_version=method["method_version"],
                    apw_windows=tuple(method["apw_windows"]),
                    n_min=int(method["n_min"]), tukey_k=float(method["tukey_k"]),
                    hampel_z=float(method["hampel_z"]), jump_sigma=float(method["jump_sigma"]),
                    dow_window=int(method["dow_window"]),
                    bootstrap_draws=draws if is_headline_cfg else 0,
                    bootstrap_seed=int(method["bootstrap_seed"]),
                    ci_level=float(method["ci_level"]),
                    omega=omega, omega_preset=preset, variant=variant, basis=basis,
                    base_period=method.get("base_period"),
                    min_omega_covered=float(method.get("min_omega_covered", 0.60)))

                res = compute(frame, weights, mc)
                key = f"APIx-{variant}|{basis}|{preset}"
                results[key] = res

                code = f"APIx-{variant}"
                # Headline periods that rest on too little of the lead-time
                # weight are withheld, the same way a thin cell is suppressed.
                # They are still computed, still in `res`, and the count of
                # what was withheld is returned -- they are just not published
                # under a label that claims to price the whole booking curve.
                headline = res.headline
                withheld = 0
                if "omega_covered" in headline.columns:
                    keep = headline["omega_covered"].fillna(0.0) >= mc.min_omega_covered
                    withheld = int((~keep).sum())
                    headline = headline[keep]
                    suppressed_headline[f"{code}|{basis}|{preset}"] = withheld

                for freq in ("daily", "weekly", "monthly"):
                    series = (headline if freq == "daily"
                              else to_frequency(headline, freq))
                    for _, r in series.iterrows():
                        rows.append(_row(code, r, freq, basis, preset, res, run_id, now,
                                         is_synthetic))

                # Route- and window-level detail only for the headline
                # configuration, otherwise the fact table explodes
                # combinatorially for numbers nobody queries.
                if write_detail and is_headline_cfg:
                    _write_cells(conn, res, code, basis, run_id)
                if write_detail and variant == headline_variant and preset == default_preset:
                    for _, r in res.by_apw.iterrows():
                        rows.append(_row(f"{code}:apw={int(r['apw_days'])}", r, "daily",
                                         basis, preset, res, run_id, now, is_synthetic))
                    for _, r in res.by_route.iterrows():
                        rows.append(_row(f"{code}:route={r['route']}:apw={int(r['apw_days'])}",
                                         r, "daily", basis, preset, res, run_id, now,
                                         is_synthetic))

    written = db.write_index_values(conn, rows)

    return {
        "run_id": run_id, "n_index_values": written,
        "headline_periods_withheld_low_omega": suppressed_headline,
        "quality": summarise(checks),
        "n_quotes_publishable": int(len(publishable)),
        "is_synthetic": bool(is_synthetic),
        "weights_version": weights.weights_version,
        "method_version": method["method_version"],
        "results": results,
    }


def _write_cells(conn: sqlite3.Connection, res, index_code: str, basis: str, run_id: str) -> int:
    """Persist the cell-level matched / LAF / adjusted / A detail.

    This is what the availability panel reads. Storing it means the three-line
    chart and the collapsing A area render instantly instead of re-running the
    engine per request -- which matters when it is the ninety seconds of demo
    the whole methodology argument rests on.
    """
    c = res.cells.copy()
    c["run_id"] = run_id
    c["index_code"] = index_code
    c["basis"] = basis
    c["suppressed"] = c["suppressed"].astype(int)
    # Persist the UNSMOOTHED triple so matched / LAF / adjusted are directly
    # comparable on the chart. Storing a smoothed `adjusted` against unsmoothed
    # `matched` made the two differ at availability = 1, which reads as the
    # blend violating its own reduction property when it does no such thing.
    c["adjusted_smoothed"] = c["adjusted"]
    c["adjusted"] = c["adjusted_raw"]
    cols = ["run_id", "index_code", "basis", "period", "route", "carrier", "apw_days",
            "matched", "laf", "adjusted", "adjusted_smoothed", "availability",
            "n_matched", "n_quotes", "suppressed"]
    for col in ("matched", "laf", "adjusted", "adjusted_smoothed", "availability"):
        c[col] = c[col].astype(object).where(c[col].notna(), None)
    conn.executemany(
        f"INSERT OR REPLACE INTO fact_cell_index ({','.join(cols)}) "
        f"VALUES ({','.join('?' * len(cols))})",
        c[cols].itertuples(index=False, name=None))
    conn.commit()
    return len(c)


def _row(code: str, r: pd.Series, freq: str, basis: str, preset: str, res,
         run_id: str, now: str, is_synthetic: int) -> dict:
    period = str(r["period"])
    return {
        "index_id": _index_id(code, period, freq, basis, preset,
                              res.method_version, res.weights_version),
        "index_code": code, "period": period, "frequency": freq, "basis": basis,
        "omega_preset": preset, "value": float(r["value"]),
        "se": _opt(r.get("se")), "ci_low": _opt(r.get("ci_low")), "ci_high": _opt(r.get("ci_high")),
        "n_quotes": _opti(r.get("n_quotes")), "n_cells": _opti(r.get("n_cells")),
        "coverage_pct": _opt(r.get("coverage_pct")),
        "omega_covered": _opt(r.get("omega_covered")), "is_synthetic": is_synthetic,
        "method_version": res.method_version, "weights_version": res.weights_version,
        "run_id": run_id, "computed_at_utc": now,
    }


def _opt(v):
    try:
        f = float(v)
        return None if not np.isfinite(f) else f
    except (TypeError, ValueError):
        return None


def _opti(v):
    f = _opt(v)
    return None if f is None else int(f)
