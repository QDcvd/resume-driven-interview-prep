"""Drop code-test columns and the candidate_questions table.

Revision ID: 0007_drop_code_candidates
Revises: 0006_interviews
Create Date: 2026-08-23

The 50-question objective exam no longer supports code questions (visible/hidden
test assertions) nor the AI variant -> candidate review pipeline. These were
created by migration 0003 (columns) and Base.metadata.create_all (the
candidate_questions table). Both are dropped here; guards keep it idempotent.
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_drop_code_candidates"
down_revision = "0006_interviews"
branch_labels = None
depends_on = None


def _has_column(bind: sa.Connection, table: str, column: str) -> bool:
    return any(c["name"] == column for c in sa.inspect(bind).get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.has_table(bind, "questions"):
        with op.batch_alter_table("questions") as batch_op:
            if _has_column(bind, "questions", "visible_tests"):
                batch_op.drop_column("visible_tests")
            if _has_column(bind, "questions", "hidden_tests"):
                batch_op.drop_column("hidden_tests")
    if bind.dialect.has_table(bind, "candidate_questions"):
        op.drop_table("candidate_questions")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.has_table(bind, "questions"):
        with op.batch_alter_table("questions") as batch_op:
            if not _has_column(bind, "questions", "visible_tests"):
                batch_op.add_column(
                    sa.Column("visible_tests", sa.JSON(), nullable=False, server_default="[]")
                )
            if not _has_column(bind, "questions", "hidden_tests"):
                batch_op.add_column(
                    sa.Column("hidden_tests", sa.JSON(), nullable=False, server_default="[]")
                )
    if not bind.dialect.has_table(bind, "candidate_questions"):
        op.create_table(
            "candidate_questions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "parent_question_id",
                sa.Integer(),
                sa.ForeignKey("questions.id"),
                nullable=False,
            ),
            sa.Column("stem", sa.Text(), nullable=False),
            sa.Column("type", sa.String(30), nullable=False),
            sa.Column("difficulty", sa.String(20), nullable=False),
            sa.Column("category", sa.String(40), nullable=False),
            sa.Column("options", sa.JSON(), server_default="[]"),
            sa.Column("correct_answer", sa.JSON(), nullable=True),
            sa.Column("explanation", sa.Text(), server_default=""),
            sa.Column("scoring_points", sa.JSON(), server_default="[]"),
            sa.Column("tags", sa.JSON(), server_default="[]"),
            sa.Column("source_url", sa.Text(), server_default=""),
            sa.Column("evidence_title", sa.Text(), server_default=""),
            sa.Column("evidence_excerpt", sa.Text(), server_default=""),
            sa.Column("status", sa.String(20), server_default="pending"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_candidate_questions_parent_question_id", "candidate_questions", ["parent_question_id"])
        op.create_index("ix_candidate_questions_status", "candidate_questions", ["status"])
