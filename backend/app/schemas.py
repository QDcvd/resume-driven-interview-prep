from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

QuestionType = Literal["choice", "short_answer", "project", "system_design"]
Difficulty = Literal["basic", "practical", "deep"]


class QuestionInput(BaseModel):
    external_id: str
    type: QuestionType
    difficulty: Difficulty
    category: str
    stem: str
    options: list[str] = Field(default_factory=list)
    correct_answer: Any
    explanation: str = ""
    scoring_points: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    source_url: str = ""
    verified_at: date | None = None
    is_core: bool = True
    enabled: bool = True


class QuestionImport(BaseModel):
    questions: list[QuestionInput]


class ReviewCardInput(BaseModel):
    title: str
    content: str
    category: str
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True


class ReviewCardImport(BaseModel):
    cards: list[ReviewCardInput]


class AttemptCreate(BaseModel):
    mode: str = "formal"
    question_ids: list[int] = Field(default_factory=list, max_length=100)


class AnswerInput(BaseModel):
    answer: Any = None
    flagged: bool = False
    elapsed_seconds: int = Field(default=0, ge=0)


class FailureInput(BaseModel):
    error: str


class SettingsInput(BaseModel):
    interview_date: date
    llm_max_concurrency: int = Field(default=2, ge=1, le=8)


class GradingResultInput(BaseModel):
    score: float = Field(ge=0)
    max_score: float = Field(default=10, gt=0)
    matched_points: list[str] = Field(default_factory=list)
    missing_points: list[str] = Field(default_factory=list)
    incorrect_claims: list[str] = Field(default_factory=list)
    improved_answer: str
    follow_up: str = ""
    confidence: float = Field(default=0.0, ge=0, le=1)
    source: Literal["ai", "manual"] = "ai"
    reason: str = ""


class ScoreOverrideInput(BaseModel):
    score: float = Field(ge=0)
    reason: str = Field(min_length=1, max_length=1_000)


class ResumeOut(BaseModel):
    id: int
    filename: str
    status: str
    source: str
    error: str | None = None
    structured: dict[str, Any] = Field(default_factory=dict)
    job_description: str = ""
    raw_preview: str = ""
    created_at: datetime | None = None


class LlmProviderInput(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=1, max_length=500)
    api_key: str = Field(default="", max_length=500)
    model: str = Field(min_length=1, max_length=200)


class LlmProviderOut(LlmProviderInput):
    configured: bool = False
    active: bool = False


class PlanOut(BaseModel):
    id: int
    resume_id: int
    status: str
    total: int
    generated_count: int
    error: str | None = None
    plan: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class InterviewCreate(BaseModel):
    resume_id: int | None = None


class InterviewMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class InterviewMessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime | None = None


class InterviewSessionOut(BaseModel):
    id: int
    resume_id: int
    status: str
    stage: str
    current_index: int
    follow_up_count: int
    blueprint: dict[str, Any] = Field(default_factory=dict)
    weak_areas: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


class InterviewReportOut(BaseModel):
    id: int
    session_id: int
    summary_text: str = ""
    score: float = 0.0
    questions: list[Any] = Field(default_factory=list)
    created_at: datetime | None = None
