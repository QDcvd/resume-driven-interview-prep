"""Add question_plans table for the 50-question exam plan.

Revision ID: 0005_question_plans
Revises: 0004_resumes
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_question_plans"
down_revision: str | None = "0004_resumes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.has_table(bind, "question_plans"):
        return
    op.create_table(
        "question_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("resume_id", sa.Integer(), sa.ForeignKey("resumes.id"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("plan_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("generated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_question_plans_resume_id", "question_plans", ["resume_id"])
    op.create_index("ix_question_plans_status", "question_plans", ["status"])


def downgrade() -> None:
    op.drop_index("ix_question_plans_status", table_name="question_plans")
    op.drop_index("ix_question_plans_resume_id", table_name="question_plans")
    op.drop_table("question_plans")
