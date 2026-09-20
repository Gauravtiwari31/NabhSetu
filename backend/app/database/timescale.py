"""Timescale hypertable installation for time-series facts."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

HYPERTABLES = (
    ("raw_observations", "collected_at"),
    ("normalised_observations", "collected_at"),
    ("published_index_values", "created_at"),
    ("elementary_cells", "created_at"),
)


def install_hypertables(bind: Connection) -> None:
    if bind.dialect.name != "postgresql":
        return
    try:
        bind.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
        for table, column in HYPERTABLES:
            try:
                bind.execute(
                    text(
                        f"SELECT create_hypertable('{table}', '{column}', if_not_exists => TRUE)"
                    )
                )
            except Exception as e:
                print(f"Skipping hypertable {table}: {e}")
    except Exception as e:
        print(f"TimescaleDB extension not available or failed: {e}")
