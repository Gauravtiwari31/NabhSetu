"""The data quality contract (Part 5, section 4).

Executable assertions that run on every ingestion batch. A BLOCK failure stops
publication -- the index is not written, and the run fails loudly. ALERT and
QUARANTINE are recorded and surfaced on /v1/coverage but do not stop the run.

The point of the contract is that the system FAILS LOUDLY AND CORRECTLY rather
than silently and wrongly. When a parser regresses, coverage visibly drops and
the affected cells are suppressed; nobody publishes a number built on a broken
parse.
"""
from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

BLOCK, ALERT, QUARANTINE = "BLOCK", "ALERT", "QUARANTINE"


def _result(check_class: str, name: str, severity: str, passed: bool,
            observed=None, detail: str = "") -> dict:
    return {"check_class": check_class, "check_name": name, "severity": severity,
            "passed": bool(passed), "observed": observed, "detail": detail}


def run_contract(quotes: pd.DataFrame, conn: Optional[sqlite3.Connection] = None,
                 expected_routes: Optional[List[str]] = None,
                 fill_target: float = 0.80) -> List[dict]:
    """Run every check and return the results. Caller decides what to do."""
    out: List[dict] = []
    n = len(quotes)

    # ---- Schema -------------------------------------------------------
    required = ["route", "carrier", "apw_days", "flight_number", "fare_family",
                "cabin", "stops", "collected_date", "departure_date", "disposition"]
    missing = [c for c in required if c not in quotes.columns]
    out.append(_result("schema", "required_columns_present", BLOCK, not missing,
                       missing, "columns missing from the batch" if missing else ""))

    if n == 0:
        out.append(_result("completeness", "batch_non_empty", BLOCK, False, 0,
                           "no quotes in batch"))
        return out

    valid_disp = {"ACCEPTED", "WINSORISED", "EXCLUDED", "QUARANTINED"}
    bad = set(quotes["disposition"].dropna().unique()) - valid_disp
    out.append(_result("schema", "disposition_domain", BLOCK, not bad, sorted(bad)))

    bad_cabin = set(quotes["cabin"].dropna().unique()) - {"economy", "other_than_economy"}
    out.append(_result("schema", "cabin_domain", BLOCK, not bad_cabin, sorted(bad_cabin)))

    pub = quotes[quotes["disposition"].isin(["ACCEPTED", "WINSORISED"])]

    # ---- Range --------------------------------------------------------
    if "base_fare" in pub.columns and "total_fare" in pub.columns and len(pub):
        base = pd.to_numeric(pub["base_fare"], errors="coerce")
        total = pd.to_numeric(pub["total_fare"], errors="coerce")
        viol = int(((base <= 0) | (base >= total)).fillna(True).sum())
        out.append(_result("range", "0_lt_base_lt_total", BLOCK, viol == 0, viol,
                           "published quotes must satisfy 0 < base_fare < total_fare"))

    # ---- Arithmetic ---------------------------------------------------
    comp_cols = ["base_fare", "yq_yr", "udf", "asf", "rcs_levy", "gst", "convenience_fee"]
    if all(c in pub.columns for c in comp_cols) and len(pub):
        recomposed = sum(pd.to_numeric(pub[c], errors="coerce").fillna(0) for c in comp_cols)
        resid = (pd.to_numeric(pub["total_fare"], errors="coerce") - recomposed).abs()
        worst = float(resid.max()) if len(resid) else 0.0
        out.append(_result("arithmetic", "components_resum_to_total", BLOCK, worst <= 1.0,
                           round(worst, 4), "|total - sum(components)| must be <= INR 1"))

    # ---- Uniqueness ---------------------------------------------------
    kappa = ["route", "carrier", "apw_days", "flight_number", "fare_family", "cabin",
             "stops", "collected_date"]
    if "source" in quotes.columns:
        dupes = int(quotes.duplicated(subset=kappa + ["source"]).sum())
        out.append(_result("uniqueness", "no_duplicate_kappa_t_source", BLOCK, dupes == 0, dupes))

    # ---- Freshness ----------------------------------------------------
    if expected_routes:
        latest = quotes["collected_date"].max()
        seen = set(quotes.loc[quotes["collected_date"] == latest, "route"].unique())
        stale = sorted(set(expected_routes) - seen)
        out.append(_result("freshness", "every_basket_route_quoted_today", ALERT,
                           not stale, len(stale),
                           f"{len(stale)} basket routes had no quote on {latest}"))

    # ---- Completeness -------------------------------------------------
    if len(pub):
        per_cell = pub.groupby(["route", "carrier", "apw_days", "collected_date"]).size()
        expected_per_cell = float(per_cell.max()) if len(per_cell) else 0.0
        fill = (per_cell / expected_per_cell) if expected_per_cell else per_cell * 0
        below = int((fill < fill_target).sum())
        out.append(_result("completeness", "cell_fill_rate", ALERT, below == 0, below,
                           f"{below} cell-days below {fill_target:.0%} of the modal cell size; "
                           f"these are suppressed, not silently averaged"))

    # ---- Distributional -----------------------------------------------
    if len(pub) and "price_T" in pub.columns:
        price = pd.to_numeric(pub["price_T"], errors="coerce")
        y = np.log(price.where(price > 0))
        med = y.groupby([pub["route"], pub["carrier"], pub["apw_days"]]).transform("median")
        sd = y.groupby([pub["route"], pub["carrier"], pub["apw_days"]]).transform("std")
        far = int((((y - med).abs() > 4 * sd) & sd.notna() & (sd > 0)).sum())
        out.append(_result("distributional", "cell_median_within_4_sigma", QUARANTINE,
                           far == 0, far))

    # ---- Referential / hash chain -------------------------------------
    if conn is not None:
        from apix_collect.provenance import verify_chain
        chain = verify_chain(conn)
        out.append(_result("referential", "provenance_hash_chain_intact", BLOCK,
                           bool(chain["intact"]), chain["first_broken_seq"],
                           f"{chain['n_records']} ledger records; tip {str(chain['tip_hash'])[:16]}..."))

        if "provenance_id" in quotes.columns:
            known = {r[0] for r in conn.execute("SELECT provenance_id FROM ledger_provenance")}
            unresolved = int((~quotes["provenance_id"].isin(known)).sum())
            out.append(_result("referential", "every_provenance_id_resolves", BLOCK,
                               unresolved == 0, unresolved))

    # ---- Cross-source measurement error -------------------------------
    if "source" in pub.columns and pub["source"].nunique() > 1:
        key = ["collected_date", "route", "carrier", "flight_number", "apw_days", "fare_family"]
        g = pub.groupby(key)["price_T"].agg(["min", "max", "size"])
        multi = g[g["size"] > 1]
        if len(multi):
            spread = ((multi["max"] - multi["min"]) / multi["min"] * 100)
            worst = float(spread.max())
            out.append(_result("cross_source", "same_flight_within_5pct", ALERT,
                               worst <= 5.0, round(worst, 3),
                               "the spread between independent sources IS our "
                               "measurement-error estimate; it is published, not hidden"))
    else:
        out.append(_result("cross_source", "same_flight_within_5pct", ALERT, True, None,
                           "only one source live; no cross-source estimate available"))

    return out


def blocking_failures(results: List[dict]) -> List[dict]:
    return [r for r in results if r["severity"] == BLOCK and not r["passed"]]


def summarise(results: List[dict]) -> Dict[str, object]:
    return {
        "n_checks": len(results),
        "n_passed": sum(1 for r in results if r["passed"]),
        "n_failed": sum(1 for r in results if not r["passed"]),
        "blocking": [r["check_name"] for r in blocking_failures(results)],
        "alerts": [r["check_name"] for r in results
                   if r["severity"] == ALERT and not r["passed"]],
    }
