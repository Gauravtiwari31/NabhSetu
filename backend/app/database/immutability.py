"""Immutability guards for ledger tables.

Corrections must append a new row with ``supersedes_id``. UPDATE/DELETE are
rejected at the database so application bugs cannot silently rewrite history.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

IMMUTABLE_TABLES = (
    "payload_artifacts",
    "raw_observations",
    "normalised_observations",
    "fare_components",
    "validation_flags",
    "provenance_records",
    "elementary_cells",
    "published_index_values",
    "quality_checks",
    "reference_observations",
    "backtest_results",
)


def install_immutability_guards(bind: Connection) -> None:
    dialect = bind.dialect.name
    if dialect == "postgresql":
        bind.execute(
            text(
                """
                CREATE OR REPLACE FUNCTION apix_forbid_mutation()
                RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION '% is immutable', TG_TABLE_NAME;
                END;
                $$ LANGUAGE plpgsql;
                """
            )
        )
        for table in IMMUTABLE_TABLES:
            bind.execute(text(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}"))
            bind.execute(
                text(
                    f"""
                    CREATE TRIGGER trg_{table}_immutable
                    BEFORE UPDATE OR DELETE ON {table}
                    FOR EACH ROW EXECUTE FUNCTION apix_forbid_mutation();
                    """
                )
            )
        return

    if dialect == "sqlite":
        for table in IMMUTABLE_TABLES:
            bind.execute(text(f"DROP TRIGGER IF EXISTS trg_{table}_no_update"))
            bind.execute(text(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete"))
            bind.execute(
                text(
                    f"""
                    CREATE TRIGGER trg_{table}_no_update
                    BEFORE UPDATE ON {table}
                    BEGIN
                        SELECT RAISE(ABORT, '{table} is immutable');
                    END;
                    """
                )
            )
            bind.execute(
                text(
                    f"""
                    CREATE TRIGGER trg_{table}_no_delete
                    BEFORE DELETE ON {table}
                    BEGIN
                        SELECT RAISE(ABORT, '{table} is immutable');
                    END;
                    """
                )
            )
