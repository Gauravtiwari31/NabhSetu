"""The APIx index engine.

    compute(quotes: DataFrame, weights: WeightSet, config: MethodConfig) -> IndexResult

Pure: no I/O, no clock, no network, no randomness beyond the seeded bootstrap.
Given the same three inputs it returns identical output, which is what
`make reproduce` relies on.

Required columns on `quotes`:
    collected_date, departure_date, route, carrier, apw_days, flight_number,
    fare_family, cabin, stops, price
Optional:
    is_sold_out, disposition   (only ACCEPTED and WINSORISED are published)
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from .aggregate import aggregate_apw, aggregate_carriers, aggregate_routes
from .availability import availability_ratio, blend
from .elementary import jevons_from_log_relatives
from .smoothing import centred_geometric_ma
from .types import CELL, FLIGHT, KAPPA, IndexResult, MethodConfig, WeightSet

REQUIRED = ["collected_date", "departure_date", "route", "carrier", "apw_days",
            "flight_number", "fare_family", "cabin", "stops", "price"]
PUBLISHABLE = {"ACCEPTED", "WINSORISED"}


def _prepare(quotes: pd.DataFrame, config: MethodConfig) -> pd.DataFrame:
    missing = [c for c in REQUIRED if c not in quotes.columns]
    if missing:
        raise ValueError("quotes is missing required columns: " + repr(missing))
    df = quotes.copy()

    # Only ACCEPTED and WINSORISED reach a published number. EXCLUDED and
    # QUARANTINED stay in the store and stay visible on /provenance, but they
    # do not move the index.
    if "disposition" in df.columns:
        df = df[df["disposition"].isin(PUBLISHABLE)]

    df = df[df["price"].notna() & (df["price"] > 0)]
    df["apw_days"] = df["apw_days"].astype(int)
    for c in ("collected_date", "departure_date"):
        df[c] = pd.to_datetime(df[c]).dt.strftime("%Y-%m-%d")

    # Dual time basis (Part 4, section 7). Booking basis attributes a quote to
    # the COLLECTION date -- "what does it cost to buy a flight today". Travel
    # basis attributes it to the DEPARTURE date -- "what is the price of air
    # travel consumed in this month", which is the CPI-consistent convention
    # the UK ONS uses.
    df["period"] = df["collected_date"] if config.basis == "book" else df["departure_date"]

    # A kappa can appear more than once in a period when two sources quote the
    # same flight. Collapse geometrically; the SPREAD between sources is kept
    # separately as the measurement-error series.
    #
    # The common case by far is exactly one quote per (kappa, period), so check
    # for duplicates first rather than paying for a groupby-apply over the
    # whole store when there is nothing to collapse.
    key = KAPPA + ["period"]
    if not df.duplicated(subset=key).any():
        df["n_sources"] = 1
        return df
    df["_log"] = np.log(df["price"])
    agg = df.groupby(key, sort=False).agg(_log=("_log", "mean"), n_sources=("price", "size"))
    agg["price"] = np.exp(agg["_log"])
    return agg.drop(columns=["_log"]).reset_index()


def _cell_indices(df: pd.DataFrame, config: MethodConfig):
    """Stage 1 plus availability, per cell per period, against the base period.

    Written as vectorised groupby aggregations rather than a per-cell Python
    loop. The identity that makes it work is that a Jevons index is an
    exponentiated MEAN of log relatives, so it decomposes into a sum and a
    count that groupby can produce directly:

        I = 100 * exp( sum(lr) / count(lr) )

    The loop version was O(cells x periods) Python iterations and did not
    survive a real backfill; this version is a handful of passes over columns.
    """
    periods = sorted(df["period"].unique())
    if not periods:
        raise ValueError("no publishable quotes: nothing to index")
    base = periods[0]

    work = df.copy()
    # Integer ids for the matching key and the flight, so joins are on ints.
    work["_kappa"] = pd.factorize(pd.MultiIndex.from_frame(work[KAPPA]))[0]
    work["_flight"] = pd.factorize(pd.MultiIndex.from_frame(work[FLIGHT]))[0]
    work["_cell"] = pd.factorize(pd.MultiIndex.from_frame(work[CELL]))[0]
    work["_logp"] = np.log(work["price"].astype(float))

    base_rows = work[work["period"] == base]
    # kappa -> log price at base; flight -> log of the lowest available fare.
    base_px = base_rows.groupby("_kappa")["_logp"].first()
    base_laf = base_rows.groupby("_flight")["price"].min()

    # --- matched (Jevons) ------------------------------------------------
    work["_p0"] = work["_kappa"].map(base_px)
    matched = work[work["_p0"].notna()].copy()
    matched["_lr"] = matched["_logp"] - matched["_p0"]

    per_flight = (matched.groupby(["period", "_cell", "_flight"], sort=False)["_lr"]
                  .agg(["sum", "count"]).reset_index())
    per_cell = (per_flight.groupby(["period", "_cell"], sort=False)[["sum", "count"]]
                .sum().reset_index())
    per_cell["matched"] = 100.0 * np.exp(per_cell["sum"] / per_cell["count"])
    per_cell = per_cell.rename(columns={"count": "n_matched"})[
        ["period", "_cell", "matched", "n_matched"]]

    # --- lowest available fare -------------------------------------------
    laf_now = (work.groupby(["period", "_cell", "_flight"], sort=False)["price"]
               .min().reset_index())
    laf_now["_base"] = laf_now["_flight"].map(base_laf)
    laf_now = laf_now[laf_now["_base"].notna()].copy()
    laf_now["_lr"] = np.log(laf_now["price"]) - np.log(laf_now["_base"])
    laf_cell = (laf_now.groupby(["period", "_cell"], sort=False)["_lr"]
                .agg(["sum", "count"]).reset_index())
    laf_cell["laf"] = 100.0 * np.exp(laf_cell["sum"] / laf_cell["count"])
    laf_cell = laf_cell[["period", "_cell", "laf"]]

    # --- availability ------------------------------------------------------
    fam = (work.groupby(["period", "_cell"], sort=False)["fare_family"]
           .nunique().reset_index(name="n_families"))
    quotes_n = (work.groupby(["period", "_cell"], sort=False).size()
                .reset_index(name="n_quotes"))
    # The cell's REFERENCE BUNDLE: the fare families the cell is known to offer,
    # taken as the maximum ever observed, so a cell whose buckets are closed in
    # every observed period is not mistaken for a cell that only ever had one.
    bundle = fam.groupby("_cell")["n_families"].max().rename("n_families_ref")

    cell_labels = work[["_cell"] + CELL].drop_duplicates().set_index("_cell")

    cells = (fam.merge(quotes_n, on=["period", "_cell"], how="outer")
                .merge(per_cell, on=["period", "_cell"], how="left")
                .merge(laf_cell, on=["period", "_cell"], how="left")
                .join(bundle, on="_cell")
                .join(cell_labels, on="_cell"))
    cells["n_matched"] = cells["n_matched"].fillna(0).astype(int)
    cells["availability"] = [
        availability_ratio(a, b) for a, b in zip(cells["n_families"], cells["n_families_ref"])]

    if config.apply_availability_adjustment:
        cells["adjusted"] = [blend(m, l, a) for m, l, a in
                             zip(cells["matched"], cells["laf"], cells["availability"])]
    else:
        cells["adjusted"] = cells["matched"]
    cells["suppressed"] = cells["n_matched"] < config.n_min
    cells["apw_days"] = cells["apw_days"].astype(int)

    # --- bootstrap blocks --------------------------------------------------
    # One entry per (period, cell): the per-flight (sum, count) pairs for the
    # matched index and the per-flight log relative for the LAF index. This is
    # all the bootstrap needs, and it is assembled from the same aggregates.
    blocks: Dict[Tuple, Dict] = {}
    if config.bootstrap_draws > 0:
        cell_key = {int(i): (v[CELL[0]], v[CELL[1]], int(v[CELL[2]]))
                    for i, v in cell_labels[CELL].to_dict("index").items()}
        avail = {(p, c): a for p, c, a in
                 zip(cells["period"], cells["_cell"], cells["availability"])}

        for (period, cid), grp in per_flight.groupby(["period", "_cell"], sort=False):
            r, c, apw = cell_key[int(cid)]
            entry = blocks.setdefault((period, r, c, apw),
                                      {"matched": {}, "laf": {}, "availability": avail.get((period, cid), 1.0)})
            for f, s, n in zip(grp["_flight"], grp["sum"], grp["count"]):
                # The bootstrap consumes (sum, count) per flight; an array of
                # that sum split into `count` equal parts is exactly equivalent
                # for a mean, and avoids materialising every log relative.
                entry["matched"][str(int(f))] = np.full(int(n), float(s) / int(n))

        for (period, cid), grp in laf_now.groupby(["period", "_cell"], sort=False):
            r, c, apw = cell_key[int(cid)]
            entry = blocks.setdefault((period, r, c, apw),
                                      {"matched": {}, "laf": {}, "availability": avail.get((period, cid), 1.0)})
            for f, v in zip(grp["_flight"], grp["_lr"]):
                entry["laf"][str(int(f))] = float(v)

    cells = cells.drop(columns=["_cell"])
    cells.attrs["base_period"] = base
    return cells, blocks


def _smooth_cells(cells: pd.DataFrame, config: MethodConfig) -> pd.DataFrame:
    """7-day centred geometric MA per cell, annihilating the weekly cycle."""
    cells = cells.sort_values(CELL + ["period"]).copy()
    cells["adjusted_raw"] = cells["adjusted"]
    if not config.apply_dow_smoothing or config.dow_window <= 1:
        return cells
    out = []
    for _, grp in cells.groupby(CELL, sort=False):
        g = grp.set_index("period")
        g["adjusted"] = centred_geometric_ma(g["adjusted"], config.dow_window).values
        out.append(g.reset_index())
    return pd.concat(out, ignore_index=True)


def _effective_weights(cells: pd.DataFrame, weights: WeightSet, omega: Dict[int, float]):
    """Collapse stages 2-4 into one weight per cell per period.

    Mathematically identical to running the three stages in sequence (the unit
    tests assert this), but it makes the bootstrap cheap: one dot product per
    draw instead of three groupbys.
    """
    live = cells[(~cells["suppressed"]) & cells["adjusted"].notna()]
    eff: Dict[str, Dict[Tuple, float]] = {}
    for period, pgrp in live.groupby("period", sort=True):
        apws = sorted({int(a) for a in pgrp["apw_days"]})
        raw = {a: float(omega.get(a, 0.0)) for a in apws}
        tot = sum(raw.values())
        om = {a: v / tot for a, v in raw.items()} if tot > 0 else {a: 1.0 / len(apws) for a in apws}

        table: Dict[Tuple, float] = {}
        for apw, agrp in pgrp.groupby("apw_days", sort=True):
            routes = sorted(agrp["route"].unique())
            wr = weights.normalised_routes(routes)
            for route, rgrp in agrp.groupby("route", sort=True):
                carriers = sorted(rgrp["carrier"].unique())
                phi = weights.normalised_carriers(route, carriers)
                for c in carriers:
                    table[(route, c, int(apw))] = om[int(apw)] * wr[route] * phi[c]
        eff[period] = table
    return eff


def _bootstrap_headline(blocks, eff, config: MethodConfig) -> pd.DataFrame:
    """Flight-block bootstrap of the headline, period by period.

    Whole flights are resampled with replacement inside each cell; the cell's
    matched and LAF indices are both recomputed from the resampled flights and
    re-blended at the observed availability; the headline is then the same dot
    product as the point estimate. Blocking on FLIGHT rather than on quote is
    the methodological point: quotes on one flight across fare families are
    strongly dependent, and an i.i.d. bootstrap would understate the interval.

    Vectorised over draws. The key identity that makes this possible: a Jevons
    index over a resampled set of flights is

        100 * exp( sum_f(chosen) sum(lr_f) / sum_f(chosen) count(lr_f) )

    so each flight collapses to the PAIR (sum of its log relatives, count of
    them) and a whole bootstrap draw is two `take`-and-sum operations. The
    naive loop was O(draws x cells x periods) in Python and did not survive a
    real backfill.
    """
    rows = []
    rng = np.random.default_rng(config.bootstrap_seed)
    alpha = (1.0 - config.ci_level) / 2.0
    draws = config.bootstrap_draws
    adjust = config.apply_availability_adjustment

    for period in sorted(eff.keys()):
        table = eff[period]
        keys = sorted(table.keys())
        if not keys:
            continue

        weights, cell_stats = [], []
        for k in keys:
            b = blocks.get((period,) + k)
            if not b:
                continue
            flights = sorted(set(b["matched"]) | set(b["laf"]))
            if not flights:
                continue
            m_sum = np.array([b["matched"][f].sum() if f in b["matched"] else 0.0
                              for f in flights])
            m_cnt = np.array([b["matched"][f].size if f in b["matched"] else 0
                              for f in flights], dtype=float)
            l_val = np.array([b["laf"].get(f, 0.0) for f in flights])
            l_has = np.array([1.0 if f in b["laf"] else 0.0 for f in flights])
            cell_stats.append((m_sum, m_cnt, l_val, l_has, float(b["availability"])))
            weights.append(table[k])

        if not cell_stats:
            rows.append({"period": period, "se": np.nan, "ci_low": np.nan, "ci_high": np.nan})
            continue

        w = np.asarray(weights, dtype=float)
        vals = np.full((draws, len(cell_stats)), np.nan)

        for i, (m_sum, m_cnt, l_val, l_has, a) in enumerate(cell_stats):
            n = m_sum.size
            pick = rng.integers(0, n, size=(draws, n))
            num = m_sum[pick].sum(axis=1)
            den = m_cnt[pick].sum(axis=1)
            with np.errstate(invalid="ignore", divide="ignore"):
                m_idx = np.where(den > 0, 100.0 * np.exp(num / np.where(den > 0, den, 1.0)), np.nan)
                lnum = l_val[pick].sum(axis=1)
                lden = l_has[pick].sum(axis=1)
                l_idx = np.where(lden > 0, 100.0 * np.exp(lnum / np.where(lden > 0, lden, 1.0)), np.nan)

            if adjust:
                both = np.isfinite(m_idx) & np.isfinite(l_idx)
                blended = np.where(both,
                                   np.exp(a * np.log(np.where(both, m_idx, 1.0))
                                          + (1.0 - a) * np.log(np.where(both, l_idx, 1.0))),
                                   np.where(np.isfinite(m_idx), m_idx, l_idx))
                vals[:, i] = blended
            else:
                vals[:, i] = m_idx

        ok = np.isfinite(vals)
        wmat = np.broadcast_to(w, vals.shape) * ok
        denom = wmat.sum(axis=1)
        stats = np.where(denom > 0,
                         (np.where(ok, vals, 0.0) * wmat).sum(axis=1) / np.where(denom > 0, denom, 1.0),
                         np.nan)

        s = stats[np.isfinite(stats)]
        if s.size >= 2:
            lo, hi = np.percentile(s, [100 * alpha, 100 * (1 - alpha)])
            rows.append({"period": period, "se": float(s.std(ddof=1)),
                         "ci_low": float(lo), "ci_high": float(hi)})
        else:
            rows.append({"period": period, "se": np.nan, "ci_low": np.nan, "ci_high": np.nan})
    return pd.DataFrame(rows, columns=["period", "se", "ci_low", "ci_high"])


def compute(quotes: pd.DataFrame, weights: WeightSet, config: MethodConfig) -> IndexResult:
    """Run the full Part 4 computation, Stage 1 through Stage 7."""
    df = _prepare(quotes, config)
    cells, blocks = _cell_indices(df, config)
    base_period = cells.attrs.get("base_period")
    cells = _smooth_cells(cells, config)

    omega = config.omega_vector()
    by_route = aggregate_carriers(cells, weights, value_col="adjusted")
    by_apw = aggregate_routes(by_route, weights)
    headline = aggregate_apw(by_apw, omega)

    eff = _effective_weights(cells, weights, omega)
    if config.bootstrap_draws > 0:
        ci = _bootstrap_headline(blocks, eff, config)
        # The bootstrap resamples the UNSMOOTHED cell indices, so its interval
        # is centred on the unsmoothed headline. The day-of-week filter is a
        # deterministic linear-in-logs operator, so the interval is transported
        # onto the published (smoothed) scale by the same multiplicative factor
        # the filter applies. Without this the published value can sit outside
        # its own confidence band, which is indefensible on a chart.
        raw_route = aggregate_carriers(cells, weights, value_col="adjusted_raw")
        raw_head = aggregate_apw(aggregate_routes(raw_route, weights), omega)
        raw_map = dict(zip(raw_head["period"], raw_head["value"]))
        headline = headline.merge(ci, on="period", how="left")
        factor = headline.apply(
            lambda r: (r["value"] / raw_map[r["period"]])
            if raw_map.get(r["period"]) not in (None, 0) and np.isfinite(raw_map.get(r["period"], np.nan))
            else 1.0, axis=1)
        for c in ("se", "ci_low", "ci_high"):
            headline[c] = headline[c] * factor
        headline["value_unsmoothed"] = headline["period"].map(raw_map)
    else:
        for c in ("se", "ci_low", "ci_high"):
            headline[c] = np.nan
        headline["value_unsmoothed"] = np.nan

    headline["n_cells"] = headline["period"].map(
        cells[~cells["suppressed"]].groupby("period").size()).fillna(0).astype(int)
    headline["n_quotes"] = headline["period"].map(
        cells.groupby("period")["n_quotes"].sum()).fillna(0).astype(int)

    n_suppressed = int(cells["suppressed"].sum())
    diagnostics = {
        "base_period": base_period,
        "n_periods": int(headline.shape[0]),
        "n_cells_total": int(cells.shape[0]),
        "n_cells_suppressed": n_suppressed,
        "suppression_pct": round(100.0 * n_suppressed / max(cells.shape[0], 1), 2),
        "mean_availability": round(float(cells["availability"].mean()), 4),
        "omega": omega,
        "n_min": config.n_min,
        "availability_adjustment": config.apply_availability_adjustment,
        "dow_smoothing": config.apply_dow_smoothing,
    }

    return IndexResult(
        headline=headline.sort_values("period").reset_index(drop=True),
        by_apw=by_apw.sort_values(["period", "apw_days"]).reset_index(drop=True),
        by_route=by_route.sort_values(["period", "route", "apw_days"]).reset_index(drop=True),
        cells=cells.sort_values(["period", "route", "carrier", "apw_days"]).reset_index(drop=True),
        diagnostics=diagnostics,
        method_version=config.method_version,
        weights_version=weights.weights_version,
        basis=config.basis,
        variant=config.variant,
        omega_preset=config.omega_preset,
    )
