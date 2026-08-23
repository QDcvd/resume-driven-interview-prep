from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(30), index=True)
    difficulty: Mapped[str] = mapped_column(String(20), index=True)
    category: Mapped[str] = mapped_column(String(40), index=True)
    stem: Mapped[str] = mapped_column(Text)
    options: Mapped[list[str]] = mapped_column(JSON, default=list)
    correct_answer: Mapped[Any] = mapped_column(JSON)
    explanation: Mapped[str] = mapped_column(Text, default="")
    scoring_points: Mapped[list[str]] = mapped_column(JSON, default=list)
    visible_tests: Mapped[list[str]] = mapped_column(JSON, default=list)
    hidden_tests: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_url: Mapped[str] = mapped_column(Text, default="")
    verified_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_core: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewCard(Base):
    __tablename__ = "review_cards"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40), index=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Attempt(Base):
    __tablename__ = "attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(String(30), default="formal")
    status: Mapped[str] = mapped_column(String(30), default="reviewing", index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=150)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    questions: Mapped[list["AttemptQuestion"]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan", order_by="AttemptQuestion.position"
    )
    answers: Mapped[list["Answer"]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan"
    )
    checkpoints: Mapped[list["Checkpoint"]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan"
    )


class AttemptQuestion(Base):
    __tablename__ = "attempt_questions"
    __table_args__ = (UniqueConstraint("attempt_id", "question_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    weight: Mapped[float] = mapped_column(default=0.0)
    attempt: Mapped[Attempt] = relationship(back_populates="questions")
    question: Mapped[Question] = relationship()


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (UniqueConstraint("attempt_id", "question_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    answer: Mapped[Any] = mapped_column(JSON, nullable=True)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    elapsed_seconds: Mapped[int] = mapped_column(Integer, default=0)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    attempt: Mapped[Attempt] = relationship(back_populates="answers")
    question: Mapped[Question] = relationship()
    grading_task: Mapped["GradingTask | None"] = relationship(
        back_populates="answer", uselist=False
    )


class Checkpoint(Base):
    __tablename__ = "checkpoints"
    __table_args__ = (UniqueConstraint("attempt_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    through_position: Mapped[int] = mapped_column(Integer)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    attempt: Mapped[Attempt] = relationship(back_populates="checkpoints")


class GradingTask(Base):
    __tablename__ = "grading_tasks"
    __table_args__ = (UniqueConstraint("answer_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    answer_id: Mapped[int] = mapped_column(ForeignKey("answers.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    answer: Mapped[Answer] = relationship(back_populates="grading_task")
    versions: Mapped[list["GradingVersion"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="GradingVersion.id"
    )


class GradingVersion(Base):
    __tablename__ = "grading_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("grading_tasks.id"), index=True)
    score: Mapped[float] = mapped_column(default=0.0)
    max_score: Mapped[float] = mapped_column(default=10.0)
    matched_points: Mapped[list[str]] = mapped_column(JSON, default=list)
    missing_points: Mapped[list[str]] = mapped_column(JSON, default=list)
    incorrect_claims: Mapped[list[str]] = mapped_column(JSON, default=list)
    improved_answer: Mapped[str] = mapped_column(Text, default="")
    follow_up: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(default=0.0)
    source: Mapped[str] = mapped_column(String(20), default="ai")
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    task: Mapped[GradingTask] = relationship(back_populates="versions")


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CandidateQuestion(Base):
    __tablename__ = "candidate_questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    parent_question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    stem: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(30))
    difficulty: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(40))
    options: Mapped[list[str]] = mapped_column(JSON, default=list)
    correct_answer: Mapped[Any] = mapped_column(JSON)
    explanation: Mapped[str] = mapped_column(Text, default="")
    scoring_points: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_url: Mapped[str] = mapped_column(Text)
    evidence_title: Mapped[str] = mapped_column(Text)
    evidence_excerpt: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QuestionMastery(Base):
    __tablename__ = "question_mastery"
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="unknown", index=True)
    streak: Mapped[int] = mapped_column(Integer, default=0)
    interval_days: Mapped[int] = mapped_column(Integer, default=0)
    due_at: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    last_result: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Resume(Base):
    """A parsed resume: raw Markdown + LLM-structured fields."""

    __tablename__ = "resumes"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    raw_markdown: Mapped[str] = mapped_column(Text, default="")
    structured_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    job_description: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="markitdown")
    status: Mapped[str] = mapped_column(String(20), default="parsing", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QuestionPlan(Base):
    """A user-confirmed distribution of the 50-question objective exam.

    status: pending (research running) | confirming (plan ready, awaiting
    user confirm) | generating (50 questions being produced) | done | failed
    """

    __tablename__ = "question_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    total: Mapped[int] = mapped_column(Integer, default=50)
    generated_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class InterviewSession(Base):
    """A mock interview run.

    status: active | ended
    stage: opening | ask | followup | closing | reporting
    current_index: index into question_plan_json["questions"]
    follow_up_count: depth of follow-ups on the current question (cap 2)
    context_summary: auto-summary of early messages beyond the sliding window
    """

    __tablename__ = "interview_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id"), index=True)
    attempt_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    stage: Mapped[str] = mapped_column(String(20), default="opening")
    current_index: Mapped[int] = mapped_column(Integer, default=0)
    follow_up_count: Mapped[int] = mapped_column(Integer, default=0)
    question_plan_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    weak_areas: Mapped[list[str]] = mapped_column(JSON, default=list)
    context_summary: Mapped[str] = mapped_column(Text, default="")
    context_summarized_upto: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    messages: Mapped[list["InterviewMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="InterviewMessage.id",
    )
    report: Mapped["InterviewReport | None"] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan"
    )


class InterviewMessage(Base):
    __tablename__ = "interview_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("interview_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # interviewer | user
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    session: Mapped[InterviewSession] = relationship(back_populates="messages")


class InterviewReport(Base):
    __tablename__ = "interview_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("interview_sessions.id"), unique=True, index=True
    )
    summary_text: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    questions_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    session: Mapped[InterviewSession] = relationship(back_populates="report")
