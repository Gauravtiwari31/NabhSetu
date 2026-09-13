"""Store access and config loading.

SQLite for the MVP so the demo runs on a cold laptop with no services. The
schema is written for a straight translation to PostgreSQL 16 + TimescaleDB;
see schema.sql.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
SCHEMA = Path(__file__).with_name("schema.sql")

IST = timezone(timedelta(hours=5, minutes=30))
EARTH_R_KM = 6371.0088


# ------------------------------------------------------------------- config

def load_config() -> Dict[str, object]:
    """Load every YAML config file once, as one dict."""
    cfg: Dict[str, object] = {}
    for name in ("method", "basket", "carriers", "charges", "sources", "airports"):
        path = CONFIG_DIR / f"{name}.yaml"
        with open(path, "r", encoding="utf-8") as fh:
            cfg[name] = yaml.safe_load(fh)
    return cfg


def db_path() -> Path:
    return Path(os.environ.get("APIX_DB", DATA_DIR / "apix.db"))


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    p = Path(path) if path else db_path()
    
    # Handle read-only file systems (like Vercel Serverless Functions)
    if p.exists() and not os.access(p.parent, os.W_OK):
        import shutil
        tmp_p = Path(f"/tmp/{p.name}")
        if not tmp_p.exists():
            shutil.copy2(p, tmp_p)
        conn = sqlite3.connect(str(tmp_p))
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(p))
        
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    _migrate(conn)
    conn.commit()


# Columns added after the first release. `CREATE TABLE IF NOT EXISTS` does
# nothing to a table that already exists, so a new column has to be added
# explicitly or an existing store silently keeps the old shape.
_ADDED_COLUMNS = {
    "fact_fare_quote": [("total_fare_capped", "REAL")],
}


def _migrate(conn: sqlite3.Connection) -> None:
    for table, columns in _ADDED_COLUMNS.items():
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


# ----------------------------------------------------------------- geography

def great_circle_km(a: Dict[str, float], b: Dict[str, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(math.sqrt(h))


def expand_basket(cfg: Dict[str, object]) -> List[dict]:
    """Expand undirected pairs into directional routes.

    Both directions of each pair are separate routes (Part 5, section 2.2):
    DEL-BOM and BOM-DEL price differently and are indexed separately.
    """
    basket = cfg["basket"]
    airports = cfg["airports"]["airports"]
    version = basket["basket_version"]
    routes: List[dict] = []
    for pair in basket["pairs"]:
        o, d = pair["origin"], pair["dest"]
        for a, b in ((o, d), (d, o)):
            routes.append({
                "route": f"{a}-{b}",
                "origin_iata": a, "dest_iata": b,
                "origin_city": airports[a]["city"], "dest_city": airports[b]["city"],
                "gc_distance_km": round(great_circle_km(airports[a], airports[b]), 1),
                "stratum": pair["stratum"],
                "is_rcs": int(bool(pair.get("is_rcs", False))),
                "in_ps_list": int(bool(pair.get("in_ps", False))),
                # Directional traffic is approximated as half the pair total.
                # [VERIFY] Replace with true directional AAI sector data when
                # available; the approximation is documented, not hidden.
                "annual_pax": int(pair["annual_pax"] / 2),
                "basket_version": version,
            })
    return routes


# ------------------------------------------------------------------ seeding

def seed_dimensions(conn: sqlite3.Connection, cfg: Dict[str, object]) -> Dict[str, int]:
    """Load routes, carriers, sources and the SCD charge tables from config."""
    counts: Dict[str, int] = {}

    routes = expand_basket(cfg)
    total_pax = sum(r["annual_pax"] for r in routes) or 1
    for r in routes:
        r["weight_wr"] = r["annual_pax"] / total_pax
    conn.executemany(
        """INSERT OR REPLACE INTO dim_route
           (route, origin_iata, dest_iata, origin_city, dest_city, gc_distance_km,
            stratum, is_rcs, in_ps_list, annual_pax, weight_wr, basket_version)
           VALUES (:route,:origin_iata,:dest_iata,:origin_city,:dest_city,:gc_distance_km,
                   :stratum,:is_rcs,:in_ps_list,:annual_pax,:weight_wr,:basket_version)""",
        routes)
    counts["dim_route"] = len(routes)

    carriers = cfg["carriers"]["carriers"]
    as_of = cfg["carriers"].get("as_of_month")
    conn.executemany(
        """INSERT OR REPLACE INTO dim_carrier
           (iata, icao, name, model, national_share, plf, avg_seats, as_of_month)
           VALUES (?,?,?,?,?,?,?,?)""",
        [(c["iata"], c.get("icao"), c["name"], c.get("model"), c.get("national_share"),
          c.get("plf"), c.get("avg_seats"), as_of) for c in carriers])
    counts["dim_carrier"] = len(carriers)

    sources = cfg["sources"]["sources"]
    conn.executemany(
        """INSERT OR REPLACE INTO dim_source
           (name, type, ladder_rung, legal_basis, tos_url, enabled)
           VALUES (?,?,?,?,?,?)""",
        [(s["name"], s["type"], s["rung"], s["legal_basis"], s.get("tos_url"),
          int(bool(s.get("enabled", False)))) for s in sources])
    counts["dim_source"] = len(sources)

    ch = cfg["charges"]
    conn.execute("DELETE FROM scd_airport_charges")
    conn.executemany(
        """INSERT INTO scd_airport_charges
           (airport_iata, udf_domestic, asf, effective_from, effective_to, source_notification_url)
           VALUES (?,?,?,?,NULL,?)""",
        [(code, float(udf), float(ch["asf_domestic_inr"]), ch["udf_effective_from"], ch["udf_source"] if "udf_source" in ch else ch["asf_source"])
         for code, udf in ch["udf_domestic_inr"].items()])
    counts["scd_airport_charges"] = len(ch["udf_domestic_inr"])

    conn.execute("DELETE FROM scd_tax_rate")
    conn.executemany(
        """INSERT INTO scd_tax_rate (cabin, gst_rate, effective_from, effective_to, notification_ref)
           VALUES (?,?,?,?,?)""",
        [(t["cabin"], float(t["gst_rate"]), t["effective_from"], t.get("effective_to"),
          t.get("notification_ref")) for t in ch["tax_rates"]])
    counts["scd_tax_rate"] = len(ch["tax_rates"])

    conn.commit()
    return counts


def seed_dim_date(conn: sqlite3.Connection, start: date, end: date,
                  holidays: Optional[Dict[str, str]] = None) -> int:
    """Populate dim_date. Holidays feed the Holiday regressor in the elasticity fit."""
    holidays = holidays or {}
    rows = []
    d = start
    while d <= end:
        key = d.isoformat()
        rows.append((key, d.weekday(), int(d.weekday() >= 5), int(key in holidays),
                     holidays.get(key), 0, 0))
        d += timedelta(days=1)
    conn.executemany(
        """INSERT OR REPLACE INTO dim_date
           (date_sk, dow, is_weekend, is_holiday, festival_name, is_long_weekend, school_vacation_flag)
           VALUES (?,?,?,?,?,?,?)""", rows)
    conn.commit()
    return len(rows)


# ------------------------------------------------------------------ weights

def build_weights(conn: sqlite3.Connection, cfg: Dict[str, object]):
    """Derive the weight vector, or accept one supplied by PSD.

    Part 4, Stage 2/3. The within-route carrier weight is

        phi_{c|r} proportional to S_c * F_{c,r} * Seats_{c,r} * PLF_c

    which estimates PASSENGERS ACTUALLY CARRIED by carrier c on route r -- the
    economically correct weight. Under equal carrier weighting a fare move at
    SpiceJet (1.6% share) would move the index as much as one at IndiGo (67.4%).

    If config/psd_weights.yaml exists it OVERRIDES everything here. That file is
    the signed input the PS means by "an index-construction module based on PSD
    given routes and weights": PSD, not the team, owns the weights.
    """
    from apix_index.types import WeightSet

    override = CONFIG_DIR / "psd_weights.yaml"
    if override.exists():
        supplied = yaml.safe_load(override.read_text(encoding="utf-8"))
        return WeightSet(
            route_weights={str(k): float(v) for k, v in supplied["route_weights"].items()},
            carrier_weights={str(r): {str(c): float(v) for c, v in tbl.items()}
                             for r, tbl in supplied.get("carrier_weights", {}).items()},
            weights_version=supplied.get("weights_version", "psd-supplied"),
            source="PSD-supplied signed input file")

    routes = conn.execute("SELECT route, weight_wr, stratum FROM dim_route").fetchall()
    carriers = conn.execute(
        "SELECT iata, national_share, plf, avg_seats FROM dim_carrier").fetchall()

    route_weights = {r["route"]: float(r["weight_wr"] or 0.0) for r in routes}

    # Weekly frequency F_{c,r} is not published per route. It is proxied by the
    # carrier's national share, which assumes a carrier deploys capacity on a
    # route in proportion to its national position. [VERIFY] Replace with DGCA
    # schedule data when available; the approximation is documented, not hidden.
    #
    # S_c, the national-share prior, exists in the formula to SMOOTH THIN
    # ROUTES and defaults to 1.0 (off). Setting S_c = national_share as well
    # would square the share and hand IndiGo ~87% of the weight against its
    # actual ~67% of passengers. With the prior off, phi reproduces the
    # published DGCA passenger shares -- which is the sanity check to run.
    prior_on = bool(cfg["carriers"].get("apply_national_share_prior", False))
    carrier_weights: Dict[str, Dict[str, float]] = {}
    for r in routes:
        table: Dict[str, float] = {}
        for c in carriers:
            share = float(c["national_share"] or 0.0)
            seats = float(c["avg_seats"] or 0.0)
            plf = float(c["plf"] or 0.0)
            s_c = share if prior_on else 1.0
            freq_proxy = share
            table[c["iata"]] = s_c * freq_proxy * seats * plf
        total = sum(table.values()) or 1.0
        carrier_weights[r["route"]] = {k: v / total for k, v in table.items()}

    version = f"derived-{cfg['basket']['basket_version']}-{cfg['carriers']['as_of_month']}"
    return WeightSet(route_weights=route_weights, carrier_weights=carrier_weights,
                     weights_version=version,
                     source="AAI sector traffic + DGCA carrier share/PLF [VERIFY]")


# ------------------------------------------------------------------- writes

def insert_quotes(conn: sqlite3.Connection, quotes: Iterable[dict]) -> int:
    """Insert quotes. INSERT OR IGNORE gives idempotency on (kappa, date, source)."""
    cols = ["quote_id", "run_id", "collected_at_utc", "collected_at_ist", "collected_date",
            "route", "carrier", "source", "flight_number", "departure_date",
            "departure_time_local", "arrival_time_local", "apw_days", "cabin", "fare_family",
            "rbd", "stops", "currency", "total_fare", "total_fare_capped", "base_fare",
            "yq_yr", "udf", "asf",
            "rcs_levy", "gst", "convenience_fee", "seats_remaining_shown", "is_sold_out",
            "is_synthetic", "quality_flag", "disposition", "provenance_id", "raw_hash",
            "supersedes_quote_id"]
    sql = (f"INSERT OR IGNORE INTO fact_fare_quote ({','.join(cols)}) "
           f"VALUES ({','.join(':' + c for c in cols)})")
    payload = [{c: q.get(c) for c in cols} for q in quotes]
    cur = conn.executemany(sql, payload)
    conn.commit()
    return cur.rowcount


def write_index_values(conn: sqlite3.Connection, rows: List[dict]) -> int:
    cols = ["index_id", "index_code", "period", "frequency", "basis", "omega_preset",
            "value", "se", "ci_low", "ci_high", "n_quotes", "n_cells", "coverage_pct",
            "is_synthetic", "method_version", "weights_version", "run_id", "computed_at_utc"]
    sql = (f"INSERT OR REPLACE INTO fact_index_value ({','.join(cols)}) "
           f"VALUES ({','.join(':' + c for c in cols)})")
    conn.executemany(sql, [{c: r.get(c) for c in cols} for r in rows])
    conn.commit()
    return len(rows)


def record_quality(conn: sqlite3.Connection, run_id: str, results: List[dict]) -> int:
    conn.executemany(
        """INSERT INTO quality_check_result
           (run_id, checked_at, check_class, check_name, severity, passed, observed, detail)
           VALUES (?,?,?,?,?,?,?,?)""",
        [(run_id, datetime.now(timezone.utc).isoformat(), r["check_class"], r["check_name"],
          r["severity"], int(r["passed"]), json.dumps(r.get("observed")), r.get("detail"))
         for r in results])
    conn.commit()
    return len(results)


def record_config_change(conn: sqlite3.Connection, operator: str, artefact: str,
                         from_version: Optional[str], to_version: str, note: str = "") -> None:
    conn.execute(
        """INSERT INTO audit_config_change
           (changed_at, operator, artefact, from_version, to_version, note)
           VALUES (?,?,?,?,?,?)""",
        (datetime.now(timezone.utc).isoformat(), operator, artefact, from_version, to_version, note))
    conn.commit()


# -------------------------------------------------------------------- reads

def read_quotes(conn: sqlite3.Connection, publishable_only: bool = True):
    import pandas as pd
    sql = "SELECT * FROM fact_fare_quote"
    if publishable_only:
        sql += " WHERE disposition IN ('ACCEPTED','WINSORISED')"
    return pd.read_sql_query(sql, conn)


def table_count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])
