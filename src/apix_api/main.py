"""The APIx public API.

REST + SDMX-JSON. SDMX is the international standard for exchanging statistical
data and metadata and is what statistical agencies and central banks actually
consume; emitting a valid structure says "we know how official statistics moves
between institutions". An ordinary application/json shape is served alongside
it for developers who are not a central bank.

Every response that carries numbers also carries the method_version, the
weights_version, and whether the underlying quotes are synthetic. A number
without its provenance is not a statistic.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from apix_store import db

app = FastAPI(
    title="APIx -- Real-time Airfare Price Index for India",
    version="1.0.0",
    description=(
        "Daily, route-level, lead-time-resolved airfare price index, built on "
        "CPI-2024-native index-number machinery (Jevons elementary, Young/Modified "
        "Laspeyres above).\n\n"
        "**No personal data is collected, stored or inferred by this system.** "
        "Fares are not personal data, so the DPDP Act, 2023 does not attach.\n\n"
        "**Collection policy:** every quote records its source, ladder rung and legal "
        "basis in an append-only hash-chained ledger. The system does not solve CAPTCHAs, "
        "rotate IPs to evade blocks, use accounts, or continue requesting a host after a "
        "block. See /v1/methodology."
    ),
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    return JSONResponse(
        status_code=500,
        content={"status": "error", "error": str(exc), "traceback": traceback.format_exc(), "url": str(request.url)}
    )

def get_conn():
    try:
        conn = db.connect()
        try:
            yield conn
        finally:
            conn.close()
    except Exception as e:
        yield e


def _records(df: pd.DataFrame) -> List[dict]:
    """DataFrame -> JSON-safe records, with NaN/inf turned into null.

    `df.where(df.notna(), None)` is NOT enough: assigning None into a float
    column coerces straight back to NaN, and json.dumps then raises
    "Out of range float values are not JSON compliant". It only shows up on
    columns that are PARTIALLY null, which is why it hid until a CPI series
    with some published inflation values and some blanks came through.
    """
    out = df.replace([np.inf, -np.inf], np.nan)
    return [{k: (None if (isinstance(v, float) and not np.isfinite(v)) or v is pd.NaT else v)
             for k, v in rec.items()}
            for rec in out.astype(object).where(out.notna(), None).to_dict("records")]


def _meta(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT method_version, weights_version, MAX(is_synthetic) AS syn, "
        "COUNT(*) AS n FROM fact_index_value").fetchone()
    if not row or row["n"] == 0:
        return {"method_version": None, "weights_version": None, "is_synthetic": None,
                "warning": "no index has been published yet; run `python cli.py index`"}
    meta = {"method_version": row["method_version"], "weights_version": row["weights_version"],
            "is_synthetic": bool(row["syn"])}
    if meta["is_synthetic"]:
        meta["SYNTHETIC"] = ("These numbers are computed from the deterministic simulator, "
                             "not from collected fares. They demonstrate the method. "
                             "They are NOT a measurement of Indian airfares.")
    return meta


def _series(conn, index_code: str, frequency: str, basis: str, preset: str,
            date_from: Optional[str], date_to: Optional[str]) -> pd.DataFrame:
    sql = ("SELECT index_id, period, value, se, ci_low, ci_high, n_quotes, n_cells, "
           "coverage_pct, method_version, weights_version, is_synthetic "
           "FROM fact_index_value WHERE index_code=? AND frequency=? AND basis=? "
           "AND omega_preset=?")
    params: List = [index_code, frequency, basis, preset]
    if date_from:
        sql += " AND period >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND period <= ?"
        params.append(date_to)
    sql += " ORDER BY period"
    return pd.read_sql_query(sql, conn, params=params)


def _sdmx(df: pd.DataFrame, index_code: str, frequency: str, basis: str, preset: str,
          meta: dict) -> dict:
    """A minimal but structurally valid SDMX-JSON 1.0 data message."""
    freq_code = {"daily": "D", "weekly": "W", "monthly": "M"}[frequency]
    periods = list(df["period"].astype(str))
    return {
        "meta": {"schema": "https://raw.githubusercontent.com/sdmx-twg/sdmx-json/master/data-message/tools/schemas/1.0/sdmx-json-data-schema.json",
                 "id": f"APIX-{index_code}-{frequency}-{basis}-{preset}",
                 "prepared": pd.Timestamp.utcnow().isoformat(),
                 "sender": {"id": "APIX", "name": "APIx Airfare Price Index"},
                 "extra": meta},
        "data": {
            "structure": {
                "name": "APIx airfare price index",
                "dimensions": {
                    "series": [
                        {"id": "INDEX", "name": "Index", "keyPosition": 0,
                         "values": [{"id": index_code, "name": index_code}]},
                        {"id": "BASIS", "name": "Time basis", "keyPosition": 1,
                         "values": [{"id": basis.upper(), "name": basis}]},
                        {"id": "OMEGA", "name": "Lead-time weight preset", "keyPosition": 2,
                         "values": [{"id": preset.upper(), "name": preset}]},
                    ],
                    "observation": [
                        {"id": "TIME_PERIOD", "name": "Time period", "keyPosition": 3,
                         "role": "time", "values": [{"id": p, "name": p} for p in periods]}],
                },
                "attributes": {"series": [
                    {"id": "FREQ", "name": "Frequency",
                     "values": [{"id": freq_code, "name": frequency}]},
                    {"id": "UNIT_MEASURE", "name": "Unit of measure",
                     "values": [{"id": "IX", "name": "Index"}]},
                    {"id": "BASE_PER", "name": "Index base period",
                     "values": [{"id": periods[0] if periods else "", "name": "= 100"}]},
                ], "observation": []},
            },
            "dataSets": [{
                "action": "Information",
                "series": {"0:0:0": {
                    "attributes": [0, 0, 0],
                    "observations": {str(i): [None if pd.isna(v) else float(v)]
                                     for i, v in enumerate(df["value"])},
                }},
            }],
        },
    }


@app.get("/v1/index", tags=["index"])
def get_index(
    variant: str = Query("T", pattern="^[BTA]$",
                         description="B = base fare + YQ/YR; T = traveller-paid (headline); A = all-in"),
    frequency: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    basis: str = Query("book", pattern="^(book|travel)$",
                       description="book = acquisition basis; travel = CPI-consistent use basis"),
    omega_preset: str = Query("uniform"),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    format: str = Query("json", pattern="^(json|sdmx-json|csv)$"),
    conn=Depends(get_conn),
):
    """The APIx headline series."""
    code = f"APIx-{variant}"
    df = _series(conn, code, frequency, basis, omega_preset, date_from, date_to)
    if df.empty:
        raise HTTPException(404, f"no series for {code}/{frequency}/{basis}/{omega_preset}")
    meta = _meta(conn)

    if format == "sdmx-json":
        return JSONResponse(_sdmx(df, code, frequency, basis, omega_preset, meta),
                            media_type="application/vnd.sdmx.data+json;version=1.0.0")
    if format == "csv":
        return PlainTextResponse(df.to_csv(index=False), media_type="text/csv")

    has_ci = bool(df["ci_low"].notna().any())
    return {
        "index_code": code, "frequency": frequency, "basis": basis,
        "omega_preset": omega_preset, **meta,
        "uncertainty": ("flight-block bootstrap, seeded and reproducible" if has_ci else
                        "point estimates only: intervals are computed for the headline "
                        "configuration (variant T, default omega preset)"),
        "n_observations": len(df),
        "observations": _records(df),
    }


@app.get("/v1/index/routes/{route}", tags=["index"])
def get_route_index(route: str, apw_days: Optional[int] = None, basis: str = "book",
                    conn=Depends(get_conn)):
    """Route-level index. Pass apw_days to pin one advance-purchase window."""
    like = f"APIx-T:route={route}:apw=%" if apw_days is None else f"APIx-T:route={route}:apw={apw_days}"
    df = pd.read_sql_query(
        "SELECT index_code, period, value, n_quotes, coverage_pct FROM fact_index_value "
        "WHERE index_code LIKE ? AND basis = ? ORDER BY period, index_code",
        conn, params=[like, basis])
    if df.empty:
        raise HTTPException(404, f"no route series for {route}")
    df["apw_days"] = df["index_code"].str.extract(r"apw=(\d+)$").astype(int)
    info = conn.execute(
        "SELECT route, origin_city, dest_city, gc_distance_km, stratum, is_rcs, weight_wr "
        "FROM dim_route WHERE route = ?", [route]).fetchone()
    return {"route": route, "route_info": dict(info) if info else None, "basis": basis,
            **_meta(conn),
            "observations": df.drop(columns=["index_code"]).to_dict("records")}


@app.get("/v1/index/apw/{tau}", tags=["index"])
def get_apw_index(tau: int, basis: str = "book", conn=Depends(get_conn)):
    """A single advance-purchase-window series."""
    df = pd.read_sql_query(
        "SELECT period, value, n_quotes, coverage_pct FROM fact_index_value "
        "WHERE index_code = ? AND basis = ? ORDER BY period",
        conn, params=[f"APIx-T:apw={tau}", basis])
    if df.empty:
        raise HTTPException(404, f"no series for advance-purchase window T+{tau}")
    return {"apw_days": tau, "basis": basis, **_meta(conn),
            "observations": _records(df)}


@app.get("/v1/elasticity", tags=["analysis"])
def get_elasticity(route: Optional[str] = None, conn=Depends(get_conn)):
    """Fitted eta(tau), tau*, coefficients and cluster-robust standard errors."""
    from apix_pipeline import elasticity, run_index
    quotes = run_index.attach_variant_prices(db.read_quotes(conn))
    if quotes.empty:
        raise HTTPException(404, "no quotes in the store")
    try:
        fit = elasticity.fit(quotes, route=route)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "route": route or "pooled (route fixed effects)",
        **_meta(conn),
        "model": "ln p = a + b1*ln(tau) + b2*ln(tau)^2 + route FE + carrier FE + dow FE + month FE",
        "standard_errors": "clustered by flight",
        "beta1": fit.beta1, "se_beta1": fit.se_beta1,
        "beta2": fit.beta2, "se_beta2": fit.se_beta2,
        "r_squared": fit.r_squared, "adj_r_squared": fit.adj_r_squared,
        "n_obs": fit.n_obs, "n_clusters": fit.n_clusters,
        "tau_star_days": fit.tau_star, "tau_star_ci95": fit.tau_star_ci,
        "note": fit.note or None,
        "eta": [{"apw_days": t, "eta": float(fit.eta(t))} for t in (1, 7, 15, 21, 30, 45, 60)],
    }


@app.get("/v1/components", tags=["analysis"])
def get_components(date_from: Optional[str] = None, date_to: Optional[str] = None,
                   conn=Depends(get_conn)):
    """Base / YQ / UDF / ASF / RCS / GST / convenience-fee decomposition.

    The OTA convenience fee is reported as a SEPARATE distribution cost, not as
    part of the fare: it differs across OTAs for an identical seat, so it is not
    a price of air travel.
    """
    sql = ("SELECT collected_date AS period, AVG(base_fare) base_fare, AVG(yq_yr) yq_yr, "
           "AVG(udf) udf, AVG(asf) asf, AVG(rcs_levy) rcs_levy, AVG(gst) gst, "
           "AVG(convenience_fee) convenience_fee, AVG(total_fare) total_fare, COUNT(*) n "
           "FROM fact_fare_quote WHERE disposition IN ('ACCEPTED','WINSORISED')")
    params: List = []
    if date_from:
        sql += " AND collected_date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND collected_date <= ?"
        params.append(date_to)
    sql += " GROUP BY collected_date ORDER BY collected_date"
    df = pd.read_sql_query(sql, conn, params=params)
    if df.empty:
        raise HTTPException(404, "no quotes in range")
    return {**_meta(conn),
            "note": ("UDF, ASF, RCS and GST are administered prices loaded from official "
                     "notifications into effective-dated SCD tables, never scraped. The base "
                     "fare is the residual and is reconciled to within INR 1."),
            "observations": _records(df)}


@app.get("/v1/availability", tags=["analysis"])
def get_availability(route: Optional[str] = None, conn=Depends(get_conn)):
    """A_g(t) and the matched-vs-LAF spread.

    Sold-out cheap buckets are a PRICE SIGNAL, not missing data. A strictly
    matched index reports zero inflation through a surge because the only quote
    still observable never changed price; this endpoint exposes the correction.
    """
    sql = ("SELECT collected_date AS period, "
           "COUNT(DISTINCT CASE WHEN is_sold_out=0 THEN fare_family END) AS families_offered, "
           "COUNT(DISTINCT fare_family) AS families_total, "
           "SUM(is_sold_out) AS n_sold_out, COUNT(*) AS n_quotes "
           "FROM fact_fare_quote")
    params: List = []
    if route:
        sql += " WHERE route = ?"
        params.append(route)
    sql += " GROUP BY collected_date ORDER BY collected_date"
    df = pd.read_sql_query(sql, conn, params=params)
    if df.empty:
        raise HTTPException(404, "no quotes")
    df["availability_ratio"] = (df["families_offered"] / df["families_total"]).round(4)
    return {"route": route or "all routes", **_meta(conn),
            "formula": "I_adj = (I_matched)^A * (I_LAF)^(1-A);  A=1 reduces exactly to matched",
            "observations": _records(df)}


@app.get("/v1/availability/series", tags=["analysis"])
def get_availability_series(route: Optional[str] = None, apw_days: Optional[int] = None,
                            basis: str = "book", conn=Depends(get_conn)):
    """The three lines: matched, lowest-available-fare, and availability-adjusted.

    Pick a surge and show all three with A collapsing underneath. The naive
    matched line stays flat, the LAF line spikes, and the adjusted line spikes
    correctly -- and when A returns to 1 the adjusted line lands exactly back on
    the matched line, which is the continuity property that makes the blend
    defensible rather than ad hoc.
    """
    sql = ("SELECT period, AVG(matched) matched, AVG(laf) laf, AVG(adjusted) adjusted, "
           "AVG(adjusted_smoothed) adjusted_smoothed, AVG(availability) availability, "
           "SUM(n_matched) n_matched, SUM(n_quotes) n_quotes "
           "FROM fact_cell_index WHERE basis = ? AND suppressed = 0")
    params: List = [basis]
    if route:
        sql += " AND route = ?"
        params.append(route)
    if apw_days is not None:
        sql += " AND apw_days = ?"
        params.append(apw_days)
    sql += " GROUP BY period ORDER BY period"
    df = pd.read_sql_query(sql, conn, params=params)
    if df.empty:
        raise HTTPException(404, "no cell-level detail; run `python cli.py index` first")
    df["matched_vs_adjusted"] = (df["adjusted"] - df["matched"]).round(4)
    return {"route": route or "all routes", "apw_days": apw_days, "basis": basis, **_meta(conn),
            "formula": "I_adj = I_matched^A * I_LAF^(1-A)",
            "observations": _records(df)}


@app.get("/v1/coverage", tags=["governance"])
def get_coverage(conn=Depends(get_conn)):
    """The coverage ledger: routes achieved, sources live, legal basis, fill rates.

    Coverage is reported against the FULL configured basket, not renormalised to
    100% over whatever was collected. A defensible 60% that is honestly reported
    is worth more to a ministry than an inadmissible 95%.
    """
    basket = pd.read_sql_query(
        "SELECT route, stratum, weight_wr, in_ps_list FROM dim_route", conn)
    seen = pd.read_sql_query(
        "SELECT route, COUNT(*) n_quotes, MIN(collected_date) first_seen, "
        "MAX(collected_date) last_seen FROM fact_fare_quote GROUP BY route", conn)
    merged = basket.merge(seen, on="route", how="left")
    merged["n_quotes"] = merged["n_quotes"].fillna(0).astype(int)
    merged["collected"] = merged["n_quotes"] > 0

    total_w = float(merged["weight_wr"].sum())
    got_w = float(merged.loc[merged["collected"], "weight_wr"].sum())

    sources = pd.read_sql_query(
        "SELECT name, type, ladder_rung, legal_basis, tos_url, enabled FROM dim_source "
        "ORDER BY ladder_rung", conn)
    live = pd.read_sql_query(
        "SELECT source, COUNT(*) n_records, SUM(n_quotes) n_quotes, "
        "SUM(CASE WHEN outcome='OK' THEN 1 ELSE 0 END) n_ok, "
        "SUM(CASE WHEN outcome='ROBOTS_BLOCKED' THEN 1 ELSE 0 END) n_robots_blocked, "
        "SUM(CASE WHEN outcome IN ('HARD_BLOCK','CIRCUIT_OPEN') THEN 1 ELSE 0 END) n_blocked "
        "FROM ledger_provenance GROUP BY source", conn)
    sources = sources.merge(live, left_on="name", right_on="source", how="left").drop(
        columns=["source"]).fillna(0)

    return {
        **_meta(conn),
        "basket_version": conn.execute(
            "SELECT basket_version FROM dim_route LIMIT 1").fetchone()["basket_version"],
        "routes_in_basket": int(len(merged)),
        "routes_collected": int(merged["collected"].sum()),
        "coverage_by_route_count_pct": round(100.0 * merged["collected"].mean(), 2),
        "coverage_by_traffic_weight_pct": round(100.0 * got_w / total_w, 2) if total_w else None,
        "coverage_note": ("Measured against the full configured basket. The uncollected "
                          "routes are listed so the gap is visible rather than renormalised away."),
        "ps_named_sectors_covered": int(
            merged.loc[merged["in_ps_list"] == 1, "collected"].sum()),
        "ps_named_sectors_total": int((merged["in_ps_list"] == 1).sum()),
        "by_stratum": merged.groupby("stratum").agg(
            routes=("route", "size"), collected=("collected", "sum"),
            weight=("weight_wr", "sum")).reset_index().to_dict("records"),
        "all_routes": merged["route"].tolist(),
        "uncollected_routes": merged.loc[~merged["collected"], "route"].tolist(),
        "source_ladder": sources.to_dict("records"),
    }


@app.get("/v1/backtest", tags=["analysis"])
def get_backtest(basis: str = "travel", variant: str = "T", base_year: int = 2024,
                 conn=Depends(get_conn)):
    """Agreement statistics against the official CPI comparator.

    Not an eyeballed overlay: Pearson and Spearman on levels and on month-on-month
    changes, Bland-Altman bias and limits of agreement, directional agreement, and
    RMSE against a random-walk benchmark. Reported whether or not they flatter the
    index -- and refused outright when the overlap is too short to support them.
    """
    from apix_pipeline import backtest
    from apix_reference import cpi

    cfg = db.load_config()
    preset = cfg["method"]["default_omega_preset"]
    apix = pd.read_sql_query(
        "SELECT period, value FROM fact_index_value WHERE index_code=? AND "
        "frequency='monthly' AND basis=? AND omega_preset=? ORDER BY period",
        conn, params=[f"APIx-{variant}", basis, preset])
    if apix.empty:
        raise HTTPException(404, "no monthly APIx series; run `python cli.py index` first")

    comp = cpi.transport_series(conn, base_year=base_year)
    if comp.empty:
        raise HTTPException(404, f"no CPI comparator for base {base_year}; "
                                 f"run `python cli.py load-cpi`")

    syn = bool(conn.execute(
        "SELECT MAX(is_synthetic) s FROM fact_index_value").fetchone()["s"])
    level = "division" if base_year == 2024 else "subgroup"
    name = f"CPI-{base_year} {cpi.TRANSPORT_LABEL[base_year]} (All India, Combined)"

    res = backtest.run(conn, apix, comp, apix_code=f"APIx-{variant}", apix_basis=basis,
                       comparator_name=name, comparator_level=level,
                       is_synthetic=syn, persist=False)
    res["air_fare_item_available"] = bool(len(cpi.find_air_fare_item(conn)))
    return res


@app.get("/v1/cpi", tags=["analysis"])
def get_cpi(base_year: int = 2024, label: Optional[str] = None,
            sector: str = "Combined", state: str = "All India",
            conn=Depends(get_conn)):
    """The loaded official CPI reference series."""
    from apix_reference import cpi
    df = cpi.transport_series(conn, base_year=base_year, state=state,
                              sector=sector, label=label)
    if df.empty:
        raise HTTPException(404, "no such CPI series loaded")
    return {"base_year": base_year, "state": state, "sector": sector,
            "label": label or cpi.TRANSPORT_LABEL.get(base_year),
            "source": "MoSPI published CPI release; loaded from file, never scraped",
            "n_observations": len(df),
            "observations": _records(df)}


@app.get("/v1/provenance/{index_id}", tags=["governance"])
def get_provenance(index_id: str, conn=Depends(get_conn)):
    """The full audit chain behind one published number."""
    row = conn.execute(
        "SELECT * FROM fact_index_value WHERE index_id = ?", [index_id]).fetchone()
    if not row:
        raise HTTPException(404, f"no published index value with id {index_id}")
    v = dict(row)

    quotes = conn.execute(
        "SELECT COUNT(*) n, COUNT(DISTINCT route) r, COUNT(DISTINCT source) s, "
        "COUNT(DISTINCT provenance_id) p FROM fact_fare_quote "
        "WHERE collected_date = ? AND disposition IN ('ACCEPTED','WINSORISED')",
        [v["period"]]).fetchone()

    ledger = pd.read_sql_query(
        "SELECT provenance_id, seq, source, ladder_rung, legal_basis, "
        "robots_directive_applied, outcome, http_status, n_quotes, fetched_at, "
        "prev_hash, this_hash FROM ledger_provenance WHERE provenance_id IN "
        "(SELECT DISTINCT provenance_id FROM fact_fare_quote WHERE collected_date = ?) "
        "ORDER BY seq", conn, params=[v["period"]])

    from apix_collect.provenance import verify_chain
    chain = verify_chain(conn)

    return {
        "index_value": v,
        "quotes_behind_it": {"n_quotes": quotes["n"], "n_routes": quotes["r"],
                             "n_sources": quotes["s"], "n_provenance_records": quotes["p"]},
        "hash_chain": chain,
        "ledger_segment": ledger.to_dict("records"),
        "note": ("Every fetch is recorded whether it succeeded or not, including requests "
                 "that were never issued because robots.txt disallowed them. That is the "
                 "point: we can prove what we did not do."),
    }


@app.get("/v1/methodology", tags=["governance"])
def get_methodology(conn=Depends(get_conn)):
    """Machine-readable method and weight versions in force."""
    try:
        cfg = db.load_config()
        weights = db.build_weights(conn, cfg)
        return {
            **_meta(conn),
        "elementary_formula": "Jevons (geometric mean of price relatives)",
        "elementary_rationale": ("MoSPI uses Jevons for CPI 2024; it satisfies time reversal "
                                 "and transitivity; fares are approximately lognormal."),
        "aggregation": {
            "stage_1": "Jevons within cell g=(route, carrier, apw), matched on kappa",
            "stage_1b": "availability adjustment: I_adj = I_matched^A * I_LAF^(1-A)",
            "stage_1c": "7-day centred geometric moving average (annihilates the weekly cycle)",
            "stage_2": "carrier aggregation with phi_{c|r} from share x seats x PLF",
            "stage_3": "route aggregation with w_r from AAI/DGCA sector traffic",
            "stage_4": "lead-time aggregation with omega_tau (a declared policy parameter)",
        },
        "matching_key": ["route", "carrier", "apw_days", "flight_number", "fare_family",
                         "cabin", "stops"],
        "apw_windows": cfg["method"]["apw_windows"],
        "n_min_per_cell": cfg["method"]["n_min"],
        "omega_presets": cfg["method"]["omega_presets"],
        "omega_caveat": ("The booking lead-time distribution for India is not public. DGCA "
                         "requested ticket-level data in December 2024 and the Federation of "
                         "Indian Airlines declined on commercial-confidentiality grounds. "
                         "omega_tau is therefore a DECLARED, VERSIONED POLICY PARAMETER, not a "
                         "measurement. The index is published under all three presets and the "
                         "spread between them IS the sensitivity analysis."),
        "weights_version": weights.weights_version,
        "weights_source": weights.source,
        "weights_are_injectable": ("Place config/psd_weights.yaml to override every derived "
                                   "weight. PSD, not this team, owns the weights."),
        "collection_policy": {
            "will_not": ["solve, bypass or outsource a CAPTCHA",
                         "rotate IPs to evade a block",
                         "create or use accounts to obtain fares",
                         "spoof headers or fingerprints after a block",
                         "continue requesting a host after a 429/403"],
            "will": ["honour robots.txt as binding policy and snapshot it",
                     "declare a truthful, contactable User-Agent",
                     "enforce a per-host token bucket below any declared crawl-delay",
                     "hold at most one in-flight request per host",
                     "trip a circuit breaker on the first hard block and escalate to a human",
                     "collect logged-out only",
                     "record the legal basis of every single quote"],
            "rationale": ("The problem statement asks for CAPTCHA handling AND terms-of-service "
                          "compliance. Those are mutually exclusive: a CAPTCHA is a technical "
                          "access control, so defeating it is unauthorised access under s.43 of "
                          "the IT Act, 2000. We resolved the contradiction the way a government "
                          "statistical product has to."),
        },
        "personal_data": "None collected, stored or inferred. DPDP Act, 2023 does not attach.",
    }
    except Exception as e:
        import traceback
        return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}


@app.get("/health", tags=["ops"])
def health(conn=Depends(get_conn)):
    if isinstance(conn, Exception):
        return {"status": "error", "error_type": "db_connect", "error": str(conn), "db_path": str(db.db_path()), "exists": db.db_path().exists()}
    try:
        return {"status": "ok", "quotes": db.table_count(conn, "fact_fare_quote"),
                "index_values": db.table_count(conn, "fact_index_value"),
                "ledger_records": db.table_count(conn, "ledger_provenance")}
    except Exception as e:
        import traceback
        return {"status": "error", "error": str(e), "traceback": traceback.format_exc(), "db_path": str(db.db_path()), "exists": db.db_path().exists()}


DASHBOARD = ROOT / "dashboard"
if DASHBOARD.exists():
    app.mount("/dashboard", StaticFiles(directory=str(DASHBOARD), html=True), name="dashboard")


@app.get("/", include_in_schema=False)
def root():
    return HTMLResponse(
        '<meta http-equiv="refresh" content="0; url=/dashboard/">'
        '<p>APIx. <a href="/dashboard/">Dashboard</a> | <a href="/docs">API docs</a></p>')

@app.get("/debug", tags=["ops"])
def debug(conn=Depends(get_conn)):
    import os
    from apix_store import db
    data_dir = str(db.DATA_DIR)
    config_dir = str(db.CONFIG_DIR)
    
    data_files = []
    if os.path.exists(data_dir):
        data_files = os.listdir(data_dir)
        
    config_files = []
    if os.path.exists(config_dir):
        config_files = os.listdir(config_dir)
        
    conn_type = str(type(conn))
    conn_str = str(conn) if isinstance(conn, Exception) else "connected"
    
    return {
        "cwd": os.getcwd(),
        "__file__": __file__,
        "data_dir": data_dir,
        "data_files": data_files,
        "config_dir": config_dir,
        "config_files": config_files,
        "db_path": str(db.db_path()),
        "db_exists": db.db_path().exists(),
        "is_writable": os.access(db.db_path().parent, os.W_OK),
        "conn_type": conn_type,
        "conn_error": conn_str
    }

