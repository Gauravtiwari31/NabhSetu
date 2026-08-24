"""MoSPI CPI reference loader.

Normalises the published CPI workbooks into one tidy table. Three different
release shapes are handled, because MoSPI has changed both the base year and
the column layout across series:

    base 2024  (cpi_96)   division level        2025-2026   'division' column
    base 2012  (cpi_554)  group/subgroup level  2013-2025   'group'/'subgroup'
    base 2010  (cpi_544)  group/subgroup level  2011-2014   'group'/'subgroup'

WHAT THIS DATA IS, AND IS NOT
-----------------------------
It is the CPI index itself: the BACK-TEST COMPARATOR and the nowcast TARGET.
It is not airfare data and contains no fare quotes.

The deepest transport granularity actually present is:
    base 2024 -> division  'Transport'
    base 2012 -> subgroup  'Transport and Communication'

There is NO 'passenger transport by air' item index in these extracts, so the
back-test compares APIx against the Transport aggregate, not against the air
fare item. That is a weaker comparison and must be reported as such -- the air
fare item is a small slice of Transport, so agreement is diluted by road fuel,
rail fares and vehicle prices, all of which move for unrelated reasons.

To compare against the air fare item proper, an item-level extract is needed
from https://cpi.mospi.gov.in (item-level series, COICOP sub-class 07.3.3).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}

# The transport aggregate under each base year, in the label vocabulary that
# base actually uses.
TRANSPORT_LABEL = {
    2024: "Transport",
    2012: "Transport and Communication",
    2010: "Transport and Communication",
}


def _month_number(value) -> Optional[int]:
    if pd.isna(value):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        n = int(value)
        return n if 1 <= n <= 12 else None
    key = str(value).strip().title()
    if key in MONTHS:
        return MONTHS[key]
    # Some releases abbreviate.
    for name, n in MONTHS.items():
        if name.lower().startswith(key.lower()[:3]):
            return n
    return None


def _tidy(df: pd.DataFrame, base_year: int, source_file: str) -> pd.DataFrame:
    """Melt one workbook's native shape into the common tidy form."""
    out = pd.DataFrame()
    out["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    out["month"] = df["month"].map(_month_number).astype("Int64")
    out["state"] = df["state"].astype(str).str.strip()
    out["sector"] = df["sector"].astype(str).str.strip()

    # Level and label: take the DEEPEST populated level available per row, so a
    # release that carries item detail is not silently flattened to division.
    level_cols = [("item", "item"), ("sub_class", "sub_class"), ("class", "class"),
                  ("subgroup", "subgroup"), ("group", "group"), ("division", "division")]
    present = [(name, col) for name, col in level_cols
               if col in df.columns and df[col].notna().any()]
    if not present:
        raise ValueError(f"{source_file}: no populated classification level found")

    label = pd.Series(pd.NA, index=df.index, dtype=object)
    level = pd.Series(pd.NA, index=df.index, dtype=object)
    for name, col in present:                      # deepest first
        fill = label.isna() & df[col].notna()
        label = label.where(~fill, df[col].astype(str).str.strip())
        level = level.where(~fill, name)
    out["level"] = level
    out["label"] = label

    out["code"] = df["code"].astype(str).str.strip() if "code" in df.columns else None
    out["idx"] = pd.to_numeric(df["index"], errors="coerce")
    out["inflation"] = pd.to_numeric(df.get("inflation"), errors="coerce")
    out["base_year"] = base_year
    out["source_file"] = source_file

    out = out[out["year"].notna() & out["month"].notna() & out["label"].notna()]
    out["period"] = (out["year"].astype(int).astype(str) + "-"
                     + out["month"].astype(int).astype(str).str.zfill(2) + "-01")
    return out


def load_workbook(path: Path) -> pd.DataFrame:
    """Read one CPI workbook and return it in tidy form."""
    path = Path(path)
    xl = pd.ExcelFile(path)
    frames: List[pd.DataFrame] = []
    for sheet in xl.sheet_names:
        df = pd.read_excel(path, sheet_name=sheet)
        cols = {c.lower().strip(): c for c in df.columns.astype(str)}
        # Only the long-format sheets carry a usable classification. The
        # dashboard summary sheets are pivoted presentation tables and are
        # skipped rather than guessed at.
        if not ({"year", "month", "state", "sector", "index"} <= set(cols)):
            continue
        df = df.rename(columns={v: k for k, v in cols.items()})
        base = int(pd.to_numeric(df.get("baseyear", df.get("base_year")),
                                 errors="coerce").dropna().iloc[0])
        frames.append(_tidy(df, base, path.name))
    if not frames:
        raise ValueError(f"{path.name}: no long-format sheet with the expected columns")
    return pd.concat(frames, ignore_index=True)


def load_directory(conn: sqlite3.Connection, directory: Path) -> Dict[str, object]:
    """Load every CPI workbook in a directory into fact_cpi_reference."""
    directory = Path(directory)
    files = sorted(p for p in directory.glob("*.xlsx") if not p.name.startswith("~$"))
    if not files:
        raise FileNotFoundError(f"no .xlsx files in {directory}")

    now = datetime.now(timezone.utc).isoformat()
    summary = {"files": {}, "rows_loaded": 0, "skipped": []}

    for path in files:
        try:
            tidy = load_workbook(path)
        except Exception as e:
            summary["skipped"].append({"file": path.name, "reason": f"{type(e).__name__}: {e}"})
            continue

        rows = [(int(r.base_year), r.period, int(r.year), int(r.month), r.state, r.sector,
                 r.level, r.label, (None if pd.isna(r.code) else str(r.code)),
                 (None if pd.isna(r.idx) else float(r.idx)),
                 (None if pd.isna(r.inflation) else float(r.inflation)),
                 r.source_file, now)
                for r in tidy.itertuples(index=False)]
        conn.executemany(
            "INSERT OR REPLACE INTO fact_cpi_reference "
            "(base_year, period, year, month, state, sector, level, label, code, "
            " idx, inflation, source_file, loaded_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
        summary["files"][path.name] = {
            "rows": len(tidy),
            "base_year": sorted(tidy.base_year.unique().tolist()),
            "levels": sorted(tidy.level.unique().tolist()),
            "period_range": [tidy.period.min(), tidy.period.max()],
            "labels": int(tidy.label.nunique()),
        }
        summary["rows_loaded"] += len(tidy)

    return summary


def transport_series(conn: sqlite3.Connection, base_year: int = 2024,
                     state: str = "All India", sector: str = "Combined",
                     label: Optional[str] = None) -> pd.DataFrame:
    """The CPI transport series for a base year: the back-test comparator.

    Returns period, idx, inflation -- sorted, one row per month.
    """
    label = label or TRANSPORT_LABEL.get(base_year, "Transport")
    df = pd.read_sql_query(
        "SELECT period, idx, inflation FROM fact_cpi_reference "
        "WHERE base_year=? AND state=? AND sector=? AND label=? "
        "ORDER BY period", conn, params=[base_year, state, sector, label])
    return df


def available_series(conn: sqlite3.Connection) -> pd.DataFrame:
    """What was actually loaded, so the back-test can pick a real comparator."""
    return pd.read_sql_query(
        "SELECT base_year, level, label, sector, COUNT(*) n, "
        "MIN(period) first_period, MAX(period) last_period "
        "FROM fact_cpi_reference WHERE state='All India' "
        "GROUP BY base_year, level, label, sector ORDER BY base_year, label, sector", conn)


def find_air_fare_item(conn: sqlite3.Connection) -> pd.DataFrame:
    """Look for an air-fare item series, if one was ever loaded.

    Returns empty when the extracts only go down to the Transport aggregate --
    which is the case for the workbooks shipped so far. The back-test reports
    that explicitly rather than quietly substituting the aggregate.
    """
    return pd.read_sql_query(
        "SELECT DISTINCT base_year, level, label FROM fact_cpi_reference "
        "WHERE LOWER(label) LIKE '%air%' ORDER BY base_year, label", conn)
