"""Add per-attempt duration for quick and expression modes.

Revision ID: 0002_attempt_duration
Revises: 0001_initial
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_attempt_duration"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("attempts") as batch:
        batch.add_column(
            sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="150")
        )


def downgrade() -> None:
    with op.batch_alter_table("attempts") as batch:
        batch.drop_column("duration_minutes")
