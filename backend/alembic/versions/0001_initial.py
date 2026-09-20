"""Initial acquisition schema, immutability guards, and Timescale hypertables.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-20
"""

from collections.abc import Sequence

from alembic import op

from app.database.base import Base
from app.database.immutability import install_immutability_guards
from app.database.models import *  # noqa: F403
from app.database.timescale import install_hypertables

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    install_immutability_guards(bind)
    install_hypertables(bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
