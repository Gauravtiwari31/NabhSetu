"""Timescale hypertable installation for time-series facts."""

from __future__ import annotations
from sqlalchemy.engine import Connection

HYPERTABLES = (
    ("raw_observations", "collected_at"),
    ("normalised_observations", "collected_at"),
    ("published_index_values", "created_at"),
    ("elementary_cells", "created_at"),
)

def install_hypertables(bind: Connection) -> None:
    # SIH Deployment: Disabled hypertable creation to prevent 
    # 'transaction aborted' errors on standard PostgreSQL instances.
    pass
