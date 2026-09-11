"""Collection runner: source ladder -> governor -> ledger -> clean -> store.

The ladder is walked in rung order. A rung that is disabled, unkeyed, or blocked
is recorded in the provenance ledger and the run CONTINUES to the next rung --
coverage degrades visibly rather than the run failing silently.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

import pandas as pd

from apix_collect.politeness import PolitenessGovernor
from apix_collect.provenance import ProvenanceLedger, payload_hash
from apix_collect.sources.synthetic import SyntheticConfig, SyntheticSource, default_surges
from apix_pipeline.clean import clean, disposition_summary
from apix_pipeline.decompose import ChargeBook, decompose
from apix_store import db

IST = timezone(timedelta(hours=5, minutes=30))


def new_run_id(tag: str = "collect") -> str:
    return f"{tag}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"


def _routes_and_carriers(conn) -> tuple:
    routes = [dict(r) for r in conn.execute(
        "SELECT route, origin_iata, dest_iata, gc_distance_km, is_rcs, stratum FROM dim_route")]
    carriers = [dict(c) for c in conn.execute(
        "SELECT iata, name, model, national_share, plf, avg_seats FROM dim_carrier")]
    return routes, carriers


def collect_day(conn, cfg: Dict, on: date, run_id: str,
                routes: Optional[Sequence[str]] = None,
                ledger: Optional[ProvenanceLedger] = None) -> Dict[str, object]:
    """Run one collection cycle for one calendar day.

    Returns a summary suitable for the coverage ledger.
    """
    ledger = ledger or ProvenanceLedger(conn, run_id)
    route_rows, carrier_rows = _routes_and_carriers(conn)
    distances = {r["route"]: float(r["gc_distance_km"] or 0) for r in route_rows}

    governor = PolitenessGovernor(cfg["sources"]["politeness"])
    ladder = sorted(cfg["sources"]["sources"], key=lambda s: s["rung"])

    collected: List[dict] = []
    per_source: Dict[str, dict] = {}

    for spec in ladder:
        name, rung = spec["name"], int(spec["rung"])
        if not spec.get("enabled", False):
            # A disabled rung is recorded, not skipped silently. The ledger is
            # the honest coverage story: this is WHY coverage is what it is.
            ledger.record(source=name, ladder_rung=rung, legal_basis=spec["legal_basis"],
                          outcome="ERROR", note="rung disabled in config/sources.yaml")
            per_source[name] = {"rung": rung, "enabled": False, "n_quotes": 0,
                                "outcome": "DISABLED"}
            continue

        if spec["type"] == "simulator":
            sc = SyntheticConfig(apw_windows=tuple(cfg["method"]["apw_windows"]))
            sc.surges = default_surges([r["route"] for r in route_rows])
            source = SyntheticSource(sc, route_rows, carrier_rows)
            rows = source.collect(on, routes=routes)
            pid = ledger.record(source=name, ladder_rung=rung,
                                legal_basis=spec["legal_basis"], outcome="OK",
                                robots_directive="NOT_APPLICABLE", n_quotes=len(rows),
                                note=f"deterministic simulator, seed={sc.seed}, date={on.isoformat()}")
            for r in rows:
                r["source"] = name
                r["provenance_id"] = pid
                r["raw_hash"] = payload_hash(r)
            collected.extend(rows)
            per_source[name] = {"rung": rung, "enabled": True, "n_quotes": len(rows),
                                "outcome": "OK", "legal_basis": spec["legal_basis"]}
            continue

        if spec["type"] == "public_page":
            # Every public-page fetch passes the governor first. If robots.txt
            # disallows the path the request is NEVER ISSUED.
            url = spec.get("base_url") or ""
            decision = governor.check(url) if url else None
            outcome = decision.outcome if decision else "ERROR"
            ledger.record(source=name, ladder_rung=rung, legal_basis=spec["legal_basis"],
                          outcome=outcome if outcome != "OK" else "ERROR",
                          robots_directive=decision.robots_directive if decision else "NOT_APPLICABLE",
                          note=(decision.note if decision else "no base_url configured"))
            per_source[name] = {"rung": rung, "enabled": True, "n_quotes": 0, "outcome": outcome}
            continue

        # Licensed APIs: enabled but unkeyed is a governance fact, not a crash.
        import os
        key_env = spec.get("auth_env")
        if key_env and not os.environ.get(key_env):
            ledger.record(source=name, ladder_rung=rung, legal_basis=spec["legal_basis"],
                          outcome="ERROR", note=f"no credential in {key_env}; rung skipped")
            per_source[name] = {"rung": rung, "enabled": True, "n_quotes": 0,
                                "outcome": "NO_CREDENTIAL"}
            continue
            
        if name == "duffel":
            from apix_collect.sources.duffel import DuffelSource
            source = DuffelSource(os.environ.get(key_env), route_rows)
            apw_windows = tuple(cfg["method"]["apw_windows"])
            try:
                rows = source.collect(on, routes=routes, apw_windows=apw_windows)
                pid = ledger.record(source=name, ladder_rung=rung,
                                    legal_basis=spec["legal_basis"], outcome="OK",
                                    robots_directive="NOT_APPLICABLE", n_quotes=len(rows),
                                    note=f"Duffel API, date={on.isoformat()}")
                for r in rows:
                    r["source"] = name
                    r["provenance_id"] = pid
                    r["raw_hash"] = payload_hash(r)
                collected.extend(rows)
                per_source[name] = {"rung": rung, "enabled": True, "n_quotes": len(rows),
                                    "outcome": "OK", "legal_basis": spec["legal_basis"]}
            except Exception as e:
                ledger.record(source=name, ladder_rung=rung, legal_basis=spec["legal_basis"],
                              outcome="ERROR", note=f"Duffel error: {e}")
                per_source[name] = {"rung": rung, "enabled": True, "n_quotes": 0,
                                    "outcome": "ERROR"}
            continue

        ledger.record(source=name, ladder_rung=rung, legal_basis=spec["legal_basis"],
                      outcome="ERROR", note="adapter not implemented in MVP")
        per_source[name] = {"rung": rung, "enabled": True, "n_quotes": 0,
                            "outcome": "ADAPTER_NOT_IMPLEMENTED"}

    if not collected:
        return {"run_id": run_id, "date": on.isoformat(), "n_raw": 0, "n_stored": 0,
                "sources": per_source, "dispositions": {}}

    raw = pd.DataFrame(collected)

    # Stage 0b: decompose using the effective-dated charge book.
    book = ChargeBook(conn,
                      convenience_fee=float(cfg["charges"]["convenience_fee_inr"]),
                      rcs_levy=float(cfg["charges"]["rcs_levy_inr"]))
    dec = decompose(raw, book, charge_on=on.isoformat())

    # Stage 0c/0d: gates, outliers, jump test, dispositions.
    cleaned = clean(dec, distances=distances,
                    tukey_k=float(cfg["method"]["tukey_k"]),
                    hampel_z=float(cfg["method"]["hampel_z"]),
                    jump_sigma=float(cfg["method"]["jump_sigma"]),
                    apw_windows=tuple(cfg["method"]["apw_windows"]))

    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(IST)

    # Build the insert payload with vectorised column work and one to_dict at
    # the end. Row-at-a-time iterrows() over a full collection cycle dominated
    # the whole run.
    out = cleaned.copy()
    out["quote_id"] = [str(uuid.uuid4()) for _ in range(len(out))]
    out["run_id"] = run_id
    out["collected_at_utc"] = now_utc.isoformat()
    out["collected_at_ist"] = now_ist.isoformat()
    out["currency"] = "INR"
    out["supersedes_quote_id"] = None
    if "total_fare_capped" not in out.columns:
        out["total_fare_capped"] = None
    for c in ("total_fare", "total_fare_capped", "base_fare", "yq_yr", "udf", "asf",
              "rcs_levy", "gst", "convenience_fee"):
        out[c] = pd.to_numeric(out.get(c), errors="coerce").astype(object).where(
            pd.to_numeric(out.get(c), errors="coerce").notna(), None)
    for c in ("apw_days", "stops", "is_sold_out", "is_synthetic", "seats_remaining_shown"):
        col = pd.to_numeric(out.get(c), errors="coerce")
        out[c] = col.astype("Int64").astype(object).where(col.notna(), None)
    out["quality_flag"] = out["quality_flag"].astype(object).where(
        out["quality_flag"].notna(), None)
    for c in ("departure_time_local", "arrival_time_local", "rbd"):
        if c not in out.columns:
            out[c] = None
        out[c] = out[c].astype(object).where(out[c].notna(), None)

    cols = ["quote_id", "run_id", "collected_at_utc", "collected_at_ist", "collected_date",
            "route", "carrier", "source", "flight_number", "departure_date",
            "departure_time_local", "arrival_time_local", "apw_days", "cabin", "fare_family",
            "rbd", "stops", "currency", "total_fare", "total_fare_capped", "base_fare",
            "yq_yr", "udf", "asf",
            "rcs_levy", "gst", "convenience_fee", "seats_remaining_shown", "is_sold_out",
            "is_synthetic", "quality_flag", "disposition", "provenance_id", "raw_hash",
            "supersedes_quote_id"]
    records = out[cols].to_dict("records")
    stored = db.insert_quotes(conn, records)

    return {"run_id": run_id, "date": on.isoformat(), "n_raw": len(raw), "n_stored": int(stored),
            "sources": per_source, "dispositions": disposition_summary(cleaned),
            "max_decomp_residual": float(dec["decomp_residual"].max())}


def backfill(conn, cfg: Dict, start: date, end: date, run_id: Optional[str] = None,
             routes: Optional[Sequence[str]] = None, progress=None) -> List[Dict]:
    """Run collection for every day in [start, end].

    For the synthetic rung this is the "two-track back-test" replay harness of
    Part 8: it builds a history that the index can be computed over. It is
    NOT a substitute for live collection, and every row it writes is stamped
    is_synthetic = 1 so the two can never be mixed up in a published chart.
    """
    run_id = run_id or new_run_id("backfill")
    ledger = ProvenanceLedger(conn, run_id)
    out = []
    d = start
    while d <= end:
        summary = collect_day(conn, cfg, d, run_id, routes=routes, ledger=ledger)
        out.append(summary)
        if progress:
            progress(summary)
        d += timedelta(days=1)
    return out


def _f(v):
    try:
        f = float(v)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


def _i(v):
    try:
        if v is None or pd.isna(v):
            return None
        return int(v)
    except (TypeError, ValueError):
        return None
