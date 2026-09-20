import sqlite3
import pandas as pd
from datetime import datetime
from pathlib import Path

def load_dgca(conn: sqlite3.Connection, csv_path: str | Path):
    path = Path(csv_path)
    if not path.exists():
        print(f"Warning: {path} not found. Skipping DGCA data load.")
        return 0

    df = pd.read_csv(path)
    if df.empty:
        return 0

    conn.execute("CREATE TABLE IF NOT EXISTS fact_dgca_reference (id INTEGER PRIMARY KEY, period TEXT NOT NULL, route TEXT NOT NULL, average_fare REAL NOT NULL, loaded_at TEXT NOT NULL)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_dgca_ref ON fact_dgca_reference(period, route)")

    loaded_at = datetime.utcnow().isoformat()
    rows = []
    for _, r in df.iterrows():
        rows.append((r["month"], r["route"], float(r["average_fare"]), loaded_at))
    
    conn.executemany(
        "INSERT OR REPLACE INTO fact_dgca_reference (period, route, average_fare, loaded_at) VALUES (?, ?, ?, ?)",
        rows
    )
    conn.commit()
    return len(rows)

def dgca_series(conn: sqlite3.Connection, route: str = None) -> pd.DataFrame:
    sql = "SELECT period, average_fare FROM fact_dgca_reference"
    params = []
    if route:
        sql += " WHERE route = ?"
        params.append(route)
    sql += " ORDER BY period"
    
    df = pd.read_sql_query(sql, conn, params=params)
    if not df.empty and not route:
        # If no route is specified, we group by period and average the fares across all routes
        df = df.groupby("period")["average_fare"].mean().reset_index()
    return df
