"""Add visible and hidden tests to code questions.

Revision ID: 0003_question_code_tests
Revises: 0002_attempt_duration
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_question_code_tests"
down_revision: str | None = "0002_attempt_duration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("questions") as batch:
        batch.add_column(
            sa.Column("visible_tests", sa.JSON(), nullable=False, server_default="[]")
        )
        batch.add_column(
            sa.Column("hidden_tests", sa.JSON(), nullable=False, server_default="[]")
        )


def downgrade() -> None:
    with op.batch_alter_table("questions") as batch:
        batch.drop_column("hidden_tests")
        batch.drop_column("visible_tests")
