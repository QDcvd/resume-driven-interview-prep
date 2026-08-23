"""Add resumes table for resume-driven onboarding.

Revision ID: 0004_resumes
Revises: 0003_question_code_tests
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_resumes"
down_revision: str | None = "0003_question_code_tests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.has_table(bind, "resumes"):
        # The app's Base.metadata.create_all may already have created the
        # table on an existing database; skip so `alembic upgrade head`
        # (run by start.py) stays idempotent.
        return
    op.create_table(
        "resumes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("raw_markdown", sa.Text(), nullable=False, server_default=""),
        sa.Column("structured_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("job_description", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="markitdown"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="parsing"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_resumes_status", "resumes", ["status"])


def downgrade() -> None:
    op.drop_index("ix_resumes_status", table_name="resumes")
    op.drop_table("resumes")
