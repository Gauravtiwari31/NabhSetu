"""DGCA monthly average-fare reference series.

The PS names DGCA's published monthly average fares as the back-test
comparator, which makes this the one external series the index is formally
measured against. So it carries the same provenance discipline as everything
else here: a row records the file it came from, that file's SHA-256, and the
URL it was downloaded from.

A file loaded WITHOUT a source URL is retained but flagged `is_placeholder=1`,
and the comparator refuses to serve placeholder rows unless asked explicitly.
That is deliberate. Template and hand-typed CSVs are genuinely useful while
wiring the pipeline up, and they are indistinguishable from real data once
they are numbers in a table -- so the distinction is recorded at load time,
when it is still known, instead of being argued about later.
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS fact_dgca_reference (
    id             INTEGER PRIMARY KEY,
    period         TEXT NOT NULL,
    route          TEXT NOT NULL,
    average_fare   REAL NOT NULL,
    source_file    TEXT,
    source_url     TEXT,
    content_sha256 TEXT,
    is_placeholder INTEGER NOT NULL DEFAULT 0,
    loaded_at      TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_dgca_ref ON fact_dgca_reference(period, route);
"""

_ADDED = [("source_file", "TEXT"), ("source_url", "TEXT"),
          ("content_sha256", "TEXT"), ("is_placeholder", "INTEGER NOT NULL DEFAULT 0")]


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    existing = {r[1] for r in conn.execute("PRAGMA table_info(fact_dgca_reference)")}
    for name, decl in _ADDED:
        if name not in existing:
            conn.execute(f"ALTER TABLE fact_dgca_reference ADD COLUMN {name} {decl}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalise_period(value: object) -> Optional[str]:
    """Month-start ISO date. DGCA releases vary between YYYY-MM and full dates."""
    stamp = pd.to_datetime(str(value), errors="coerce")
    if pd.isna(stamp):
        return None
    return stamp.to_period("M").to_timestamp().date().isoformat()


def load_dgca(conn: sqlite3.Connection, csv_path: str | Path,
              source_url: Optional[str] = None) -> Dict[str, object]:
    """Load one DGCA average-fare CSV. Returns a summary, never a bare count.

    Expected columns: month (or period), route, average_fare.
    """
    path = Path(csv_path)
    if not path.exists():
        return {"rows": 0, "skipped": f"{path} not found", "is_placeholder": None}

    frame = pd.read_csv(path, encoding="utf-8-sig")
    if frame.empty:
        return {"rows": 0, "skipped": f"{path.name} is empty", "is_placeholder": None}

    columns = {c.lower().strip(): c for c in frame.columns.astype(str)}
    period_col = columns.get("month") or columns.get("period")
    route_col = columns.get("route")
    fare_col = columns.get("average_fare") or columns.get("avg_fare")
    missing = [name for name, col in
               (("month/period", period_col), ("route", route_col),
                ("average_fare", fare_col)) if col is None]
    if missing:
        raise ValueError(f"{path.name}: missing required column(s): {', '.join(missing)}")

    _ensure_schema(conn)
    is_placeholder = 0 if source_url else 1
    loaded_at = datetime.now(timezone.utc).isoformat()
    checksum = _sha256(path)

    rows, dropped = [], 0
    for record in frame.to_dict("records"):
        period = _normalise_period(record[period_col])
        fare = pd.to_numeric(record[fare_col], errors="coerce")
        route = str(record[route_col]).strip().upper()
        if period is None or pd.isna(fare) or float(fare) <= 0 or not route:
            dropped += 1
            continue
        rows.append((period, route, float(fare), path.name, source_url,
                     checksum, is_placeholder, loaded_at))

    conn.executemany(
        "INSERT OR REPLACE INTO fact_dgca_reference "
        "(period, route, average_fare, source_file, source_url, content_sha256, "
        " is_placeholder, loaded_at) VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()

    return {"rows": len(rows), "dropped": dropped, "file": path.name,
            "sha256": checksum, "source_url": source_url,
            "is_placeholder": bool(is_placeholder)}


def dgca_series(conn: sqlite3.Connection, route: Optional[str] = None,
                include_placeholder: bool = False) -> pd.DataFrame:
    """The comparator series, as (period, idx).

    Placeholder rows -- loaded with no source URL -- are excluded by default so
    a hand-made CSV cannot quietly become a published agreement statistic.
    """
    _ensure_schema(conn)
    sql = "SELECT period, average_fare FROM fact_dgca_reference WHERE 1=1"
    params: list = []
    if not include_placeholder:
        sql += " AND COALESCE(is_placeholder, 0) = 0"
    if route:
        sql += " AND route = ?"
        params.append(route)
    sql += " ORDER BY period"

    frame = pd.read_sql_query(sql, conn, params=params)
    if frame.empty:
        return pd.DataFrame(columns=["period", "idx"])
    if not route:
        # Across routes the level is not meaningful on its own, so average it
        # and let the back-test rebase; it compares shapes, not rupee levels.
        frame = frame.groupby("period", as_index=False)["average_fare"].mean()
    return frame.rename(columns={"average_fare": "idx"})


def provenance(conn: sqlite3.Connection) -> pd.DataFrame:
    """What was loaded, from where, and whether it is a placeholder."""
    _ensure_schema(conn)
    return pd.read_sql_query(
        "SELECT source_file, source_url, content_sha256, is_placeholder, "
        "COUNT(*) AS n_rows, MIN(period) AS first_period, MAX(period) AS last_period, "
        "MAX(loaded_at) AS loaded_at FROM fact_dgca_reference "
        "GROUP BY source_file, source_url, content_sha256, is_placeholder "
        "ORDER BY loaded_at DESC", conn)
