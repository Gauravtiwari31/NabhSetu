"""Index publication tables, quality checks, and official-reference facts.

Revision ID: 0002_index_publication
Revises: 0001_initial
Create Date: 2026-09-20
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import Column, inspect

from app.database.immutability import install_immutability_guards
from app.database.models import *  # noqa: F403
from app.database.models.publication import (
    BacktestResult,
    BasketVersion,
    ElementaryCell,
    IndexRun,
    PublishedIndexValue,
    QualityCheck,
    ReferenceObservation,
    WeightVersion,
)
from app.database.timescale import install_hypertables
from app.database.types import enum_column
from app.domain.enums import PublicationDisposition

revision: str = "0002_index_publication"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TABLES = (
    BasketVersion.__table__,
    WeightVersion.__table__,
    IndexRun.__table__,
    ElementaryCell.__table__,
    PublishedIndexValue.__table__,
    QualityCheck.__table__,
    ReferenceObservation.__table__,
    BacktestResult.__table__,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing = set(inspector.get_table_names())
    for table in NEW_TABLES:
        if table.name not in existing:
            table.create(bind, checkfirst=True)
    columns = {column["name"] for column in inspector.get_columns("normalised_observations")}
    if "publication_disposition" not in columns:
        op.add_column(
            "normalised_observations",
            Column(
                "publication_disposition",
                enum_column(PublicationDisposition),
                nullable=False,
                server_default="accepted",
            ),
        )
    install_immutability_guards(bind)
    install_hypertables(bind)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(NEW_TABLES):
        table.drop(bind, checkfirst=True)
