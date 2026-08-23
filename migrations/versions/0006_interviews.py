"""interview_sessions / interview_messages / interview_reports

Revision ID: 0006_interviews
Revises: 0005_question_plans
Create Date: 2026-08-23

Idempotent: tables are also auto-created by Base.metadata.create_all, so each
create is guarded by a dialect.has_table check.
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_interviews"
down_revision = "0005_question_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not bind.dialect.has_table(bind, "interview_sessions"):
        op.create_table(
            "interview_sessions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("resume_id", sa.Integer(), sa.ForeignKey("resumes.id"), nullable=False),
            sa.Column("attempt_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(20), server_default="active"),
            sa.Column("stage", sa.String(20), server_default="opening"),
            sa.Column("current_index", sa.Integer(), server_default="0"),
            sa.Column("follow_up_count", sa.Integer(), server_default="0"),
            sa.Column("question_plan_json", sa.JSON(), server_default="{}"),
            sa.Column("weak_areas", sa.JSON(), server_default="[]"),
            sa.Column("context_summary", sa.Text(), server_default=""),
            sa.Column("context_summarized_upto", sa.Integer(), server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_interview_sessions_status", "interview_sessions", ["status"])
        op.create_index("ix_interview_sessions_resume_id", "interview_sessions", ["resume_id"])
    if not bind.dialect.has_table(bind, "interview_messages"):
        op.create_table(
            "interview_messages",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "session_id",
                sa.Integer(),
                sa.ForeignKey("interview_sessions.id"),
                nullable=False,
            ),
            sa.Column("role", sa.String(20), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_interview_messages_session_id", "interview_messages", ["session_id"])
    if not bind.dialect.has_table(bind, "interview_reports"):
        op.create_table(
            "interview_reports",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "session_id",
                sa.Integer(),
                sa.ForeignKey("interview_sessions.id"),
                nullable=False,
            ),
            sa.Column("summary_text", sa.Text(), server_default=""),
            sa.Column("score", sa.Float(), server_default="0"),
            sa.Column("questions_json", sa.JSON(), server_default="[]"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_interview_reports_session_id", "interview_reports", ["session_id"])


def downgrade() -> None:
    for table in ("interview_reports", "interview_messages", "interview_sessions"):
        op.drop_table(table)
