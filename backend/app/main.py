# ruff: noqa: B008
import json
import os
import random
import sqlite3
import threading
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session, selectinload

from .code_runner import run_python_submission
from .config import Settings, get_settings
from .database import Base, make_engine, make_session_factory
from .grading import GradeProvider, build_openai_grade_provider, run_pending_grading
from .interview_agent import generate_blueprint, generate_report
from .interview_runner import run_turn_events
from .llm_provider import (
    PROVIDER_SETTING_KEY,
    effective_llm_config,
    effective_llm_config_from_session,
    read_provider,
    write_provider,
)
from .models import (
    Answer,
    AppSetting,
    Attempt,
    AttemptQuestion,
    CandidateQuestion,
    Checkpoint,
    GradingTask,
    GradingVersion,
    InterviewMessage,
    InterviewReport,
    InterviewSession,
    Question,
    QuestionMastery,
    QuestionPlan,
    Resume,
    ReviewCard,
)
from .question_generator import GenerateFn, generate_for_plan
from .research_agent import ResearchFn, research_plan
from .resume_parser import ResumeParser, parse_resume
from .schemas import (
    AnswerInput,
    AttemptCreate,
    CodeRunInput,
    FailureInput,
    GradingResultInput,
    InterviewCreate,
    InterviewMessageIn,
    LlmProviderInput,
    QuestionImport,
    QuestionInput,
    ReviewCardImport,
    ScoreOverrideInput,
    SettingsInput,
    VariantRequest,
)
from .services import (
    EXAM_DURATION_MINUTES,
    EXAM_QUESTION_COUNT,
    active_plan_questions,
)
from .variants import VariantGenerator, build_variant_generator

SUBJECTIVE_TYPES = {"short_answer", "project", "system_design", "code"}


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _deadline_passed(attempt: Attempt) -> bool:
    deadline = _aware(attempt.deadline_at)
    return deadline is not None and deadline <= datetime.now(UTC)


def _public_question(question: Question, reveal: bool = False) -> dict[str, Any]:
    data = {
        "id": question.id,
        "external_id": question.external_id,
        "type": question.type,
        "difficulty": question.difficulty,
        "category": question.category,
        "stem": question.stem,
        "options": question.options,
        "tags": question.tags,
        "visible_tests": question.visible_tests,
        "source_url": question.source_url,
        "verified_at": question.verified_at.isoformat() if question.verified_at else None,
        "is_core": question.is_core,
        "enabled": question.enabled,
    }
    if reveal:
        data.update(
            correct_answer=question.correct_answer,
            explanation=question.explanation,
            scoring_points=question.scoring_points,
            hidden_tests=question.hidden_tests,
        )
    return data


def _attempt_data(
    attempt: Attempt, cards: list[ReviewCard] | None = None, reveal: bool = False
) -> dict[str, Any]:
    return {
        "id": attempt.id,
        "mode": attempt.mode,
        "status": attempt.status,
        "created_at": _aware(attempt.created_at),
        "started_at": _aware(attempt.started_at),
        "deadline_at": _aware(attempt.deadline_at),
        "submitted_at": _aware(attempt.submitted_at),
        "duration_minutes": attempt.duration_minutes,
        "questions": [
            {
                "position": item.position,
                "weight": item.weight,
                "question": _public_question(item.question, reveal=reveal),
            }
            for item in attempt.questions
        ],
        "answers": [
            {
                "id": answer.id,
                "question_id": answer.question_id,
                "answer": answer.answer,
                "flagged": answer.flagged,
                "elapsed_seconds": answer.elapsed_seconds,
                "is_correct": answer.is_correct,
                "updated_at": _aware(answer.updated_at),
                "grading": _latest_grading(answer),
                "grading_status": answer.grading_task.status if answer.grading_task else None,
            }
            for answer in attempt.answers
        ],
        "checkpoints": [
            {
                "number": cp.number,
                "through_position": cp.through_position,
                "completed_at": _aware(cp.completed_at),
            }
            for cp in attempt.checkpoints
        ],
        "review_cards": [
            _review_card_data(card)
            for card in (cards or [])
        ],
        "domain_scores": _ability_stats_for_attempt(attempt)
        if reveal and attempt.status == "submitted"
        else [],
    }


def _review_cards_for_attempt(session: Session, attempt: Attempt) -> list[ReviewCard]:
    categories = {item.question.category for item in attempt.questions}
    if not categories:
        return []
    cards = list(
        session.scalars(
            select(ReviewCard)
            .where(ReviewCard.enabled, ReviewCard.category.in_(categories))
            .order_by(ReviewCard.id)
        )
    )
    if len(cards) <= 15:
        return cards

    question_tags: dict[str, set[str]] = {}
    question_text: dict[str, str] = {}
    for category in categories:
        category_questions = [
            item.question for item in attempt.questions if item.question.category == category
        ]
        question_tags[category] = {
            str(tag).strip().casefold()
            for question in category_questions
            for tag in question.tags
            if str(tag).strip()
        }
        question_text[category] = " ".join(
            part
            for question in category_questions
            for part in [
                question.stem,
                question.explanation,
                *[str(tag) for tag in question.tags],
            ]
        ).casefold()

    def rank(card: ReviewCard) -> tuple[int, int, int]:
        tags = {str(tag).strip().casefold() for tag in card.tags if str(tag).strip()}
        exact_matches = len(tags & question_tags.get(card.category, set()))
        searchable = question_text.get(card.category, "")
        text_matches = sum(1 for tag in tags if len(tag) > 1 and tag in searchable)
        # The final key rotates equally relevant cards between attempts while remaining
        # deterministic when the same attempt is resumed.
        rotation = (
            (card.id ^ (attempt.id * 0x9E3779B1)) * 0x85EBCA6B
        ) & 0x7FFFFFFF
        return (-(exact_matches * 10 + text_matches), rotation, card.id)

    by_category = {
        category: sorted(
            [card for card in cards if card.category == category], key=rank
        )
        for category in sorted(categories)
    }
    selected: list[ReviewCard] = []
    selected_ids: set[int] = set()

    # Reserve one slot for every represented category before relevance fills the rest.
    for category in sorted(
        by_category,
        key=lambda value: (
            -sum(1 for item in attempt.questions if item.question.category == value),
            value,
        ),
    ):
        if by_category[category] and len(selected) < 15:
            card = by_category[category][0]
            selected.append(card)
            selected_ids.add(card.id)

    remaining = sorted([card for card in cards if card.id not in selected_ids], key=rank)
    selected.extend(remaining[: 15 - len(selected)])
    return selected


def _review_card_data(card: ReviewCard) -> dict[str, Any]:
    return {
        "id": card.id,
        "title": card.title,
        "content": card.content,
        "category": card.category,
        "tags": card.tags,
    }


def _grading_data(version: GradingVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "score": version.score,
        "max_score": version.max_score,
        "matched_points": version.matched_points,
        "missing_points": version.missing_points,
        "incorrect_claims": version.incorrect_claims,
        "improved_answer": version.improved_answer,
        "follow_up": version.follow_up,
        "confidence": version.confidence,
        "source": version.source,
        "reason": version.reason,
        "created_at": _aware(version.created_at),
    }


def _latest_grading(answer: Answer) -> dict[str, Any] | None:
    task = getattr(answer, "grading_task", None)
    if not task or not task.versions:
        return None
    return _grading_data(task.versions[-1])


def _attempt_score(attempt: Attempt) -> int:
    attempt_questions = {item.question_id: item for item in attempt.questions}
    total = 0.0
    for answer in attempt.answers:
        item = attempt_questions.get(answer.question_id)
        if not item:
            continue
        if item.question.type == "choice":
            if answer.is_correct:
                total += item.weight
            continue
        grading = _latest_grading(answer)
        if grading:
            total += grading["score"] / max(1, grading["max_score"]) * item.weight
    return round(total)


def _ability_stats_for_attempt(attempt: Attempt) -> list[dict[str, Any]]:
    answers = {answer.question_id: answer for answer in attempt.answers}
    totals: dict[str, dict[str, float | int]] = {}
    for item in attempt.questions:
        question = item.question
        answer = answers.get(question.id)
        normalized_score: float | None = None
        if question.type == "choice":
            if answer and answer.answer not in (None, "", []):
                normalized_score = 100.0 if answer.is_correct else 0.0
        elif answer:
            grading = _latest_grading(answer)
            if grading:
                normalized_score = (
                    grading["score"] / max(1, grading["max_score"]) * 100
                )
        if normalized_score is None:
            continue
        total = totals.setdefault(question.category, {"score": 0.0, "answered": 0})
        total["score"] = float(total["score"]) + normalized_score
        total["answered"] = int(total["answered"]) + 1
    return sorted(
        [
            {
                "name": name,
                "score": round(float(total["score"]) / int(total["answered"])),
                "answered": int(total["answered"]),
                "trend": 0,
            }
            for name, total in totals.items()
        ],
        key=lambda ability: (ability["score"], ability["name"]),
    )


def _latest_submitted_formal(session: Session) -> Attempt | None:
    return session.scalar(
        select(Attempt)
        .where(Attempt.mode == "formal", Attempt.status == "submitted")
        .order_by(Attempt.id.desc())
        .options(
            selectinload(Attempt.questions).selectinload(AttemptQuestion.question),
            selectinload(Attempt.answers)
            .selectinload(Answer.grading_task)
            .selectinload(GradingTask.versions),
        )
    )


def create_app(
    database_url: str | None = None,
    grade_provider: GradeProvider | None = None,
    variant_generator: VariantGenerator | None = None,
    resume_parser_fn: ResumeParser | None = None,
    research_fn: ResearchFn | None = None,
    generate_fn: GenerateFn | None = None,
) -> FastAPI:
    # 清理指向失效文件的 SSL 证书环境变量：若本机残留的
    # SSL_CERT_FILE / SSL_CERT_DIR 指向不存在的文件，httpx 建连会直接
    # FileNotFoundError，导致 AI 评分/变体生成 500。无效值回退到系统默认 CA。
    for _var in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
        _path = os.environ.get(_var)
        if _path and not os.path.exists(_path):
            os.environ.pop(_var, None)
    settings = Settings(database_url=database_url) if database_url else get_settings()
    settings.ensure_sqlite_directory()
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    Base.metadata.create_all(engine)
    app = FastAPI(title=settings.app_name)
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.grading_stop_event = threading.Event()
    app.state.grade_provider = grade_provider
    app.state.variant_generator = variant_generator
    app.state.resume_parser = resume_parser_fn
    app.state.research_fn = research_fn
    app.state.generate_fn = generate_fn

    def db() -> Any:
        with factory() as session:
            yield session

    def load_attempt(session: Session, attempt_id: int) -> Attempt:
        attempt = session.scalar(
            select(Attempt)
            .where(Attempt.id == attempt_id)
            .options(
                selectinload(Attempt.questions).selectinload(AttemptQuestion.question),
                selectinload(Attempt.answers)
                .selectinload(Answer.grading_task)
                .selectinload(GradingTask.versions),
                selectinload(Attempt.checkpoints),
            )
        )
        if not attempt:
            raise HTTPException(404, "考试记录不存在")
        return attempt

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/dashboard")
    def dashboard(session: Session = Depends(db)) -> dict[str, Any]:
        questions = session.scalar(select(func.count()).select_from(Question)) or 0
        attempts = session.scalar(select(func.count()).select_from(Attempt)) or 0
        pending = (
            session.scalar(
                select(func.count()).select_from(GradingTask).where(GradingTask.status == "pending")
            )
            or 0
        )
        due_count = (
            session.scalar(
                select(func.count())
                .select_from(QuestionMastery)
                .where(
                    QuestionMastery.due_at <= date.today(),
                    QuestionMastery.status != "mastered",
                )
            )
            or 0
        )
        latest = session.scalar(select(Attempt).order_by(Attempt.id.desc()))
        active = (
            latest if latest and latest.status in {"reviewing", "in_progress"} else None
        )
        latest_formal = _latest_submitted_formal(session)
        interview_value = session.get(AppSetting, "interview_date")
        interview_date = (
            date.fromisoformat(interview_value.value)
            if interview_value
            else settings.interview_date
        )
        return {
            "question_count": questions,
            "attempt_count": attempts,
            "pending_grading": pending,
            "due_count": due_count,
            "active_attempt_id": active.id if active else None,
            "active_attempt": {
                "id": active.id,
                "title": "未完成的正式考试"
                if active.mode == "formal"
                else "未完成的专项练习",
                "progress": round(
                    len(
                        [
                            answer
                            for answer in active.answers
                            if answer.answer not in (None, "", [])
                        ]
                    )
                    / max(1, len(active.questions))
                    * 100
                ),
                "remaining_seconds": active.duration_minutes * 60,
                "status": active.status,
            }
            if active
            else None,
            "latest_attempt_id": latest.id if latest else None,
            "latest_attempt_status": latest.status if latest else None,
            "recent_score": _attempt_score(latest_formal) if latest_formal else None,
            "abilities": _ability_stats_for_attempt(latest_formal)
            if latest_formal
            else [],
            "days_until_interview": max((interview_date - date.today()).days, 0),
        }

    @app.get("/api/mistakes")
    def mistakes(
        category: str | None = None, session: Session = Depends(db)
    ) -> dict[str, Any]:
        today = date.today()
        statement = (
            select(QuestionMastery, Question)
            .join(Question, Question.id == QuestionMastery.question_id)
            .where(QuestionMastery.due_at <= today, QuestionMastery.status != "mastered")
            .order_by(QuestionMastery.due_at, Question.id)
        )
        if category:
            statement = statement.where(Question.category == category)
        rows = session.execute(statement).all()
        return {
            "due_count": len(rows),
            "items": [_public_question(question, reveal=True) for _, question in rows],
        }

    @app.get("/api/stats/abilities")
    def ability_stats(session: Session = Depends(db)) -> list[dict[str, Any]]:
        latest_formal = _latest_submitted_formal(session)
        return _ability_stats_for_attempt(latest_formal) if latest_formal else []

    @app.get("/api/settings")
    def read_settings(session: Session = Depends(db)) -> dict[str, Any]:
        interview_value = session.get(AppSetting, "interview_date")
        concurrency_value = session.get(AppSetting, "llm_max_concurrency")
        return {
            "interview_date": interview_value.value
            if interview_value
            else settings.interview_date.isoformat(),
            "llm_max_concurrency": concurrency_value.value
            if concurrency_value
            else settings.llm_max_concurrency,
            "llm_model": settings.llm_model,
            "llm_configured": bool(settings.llm_api_key and settings.llm_model),
            "max_grading_batch": settings.llm_max_batch_size,
            "autosave_delay_ms": 800,
        }

    @app.put("/api/settings")
    def update_settings(payload: SettingsInput, session: Session = Depends(db)) -> dict[str, Any]:
        values: dict[str, Any] = {
            "interview_date": payload.interview_date.isoformat(),
            "llm_max_concurrency": payload.llm_max_concurrency,
        }
        for key, value in values.items():
            item = session.get(AppSetting, key)
            if item:
                item.value = value
            else:
                session.add(AppSetting(key=key, value=value))
        session.commit()
        return {
            **values,
            "llm_model": settings.llm_model,
            "llm_configured": bool(settings.llm_api_key and settings.llm_model),
            "max_grading_batch": settings.llm_max_batch_size,
            "autosave_delay_ms": 800,
        }

    @app.post("/api/settings/backup")
    def backup_now() -> dict[str, Any]:
        prefix = "sqlite:///"
        if not settings.database_url.startswith(prefix):
            raise HTTPException(409, "当前数据库不是 SQLite")
        source = Path(settings.database_url.removeprefix(prefix)).resolve()
        if not source.exists():
            raise HTTPException(404, "数据库文件尚未创建")
        backup_dir = source.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        destination = backup_dir / f"interview_exam-{datetime.now():%Y%m%d-%H%M%S}.db"
        with sqlite3.connect(source) as source_db, sqlite3.connect(destination) as target_db:
            source_db.backup(target_db)
        backups = sorted(backup_dir.glob("interview_exam-*.db"), reverse=True)
        for old_backup in backups[10:]:
            old_backup.unlink()
        return {"created": True, "filename": destination.name}

    @app.post("/api/code/run")
    def code_run(payload: CodeRunInput, session: Session = Depends(db)) -> dict[str, Any]:
        visible_tests = payload.visible_tests
        hidden_tests = payload.hidden_tests
        if payload.question_id is not None:
            question = session.get(Question, payload.question_id)
            if not question or question.type != "code":
                raise HTTPException(404, "代码题不存在")
            visible_tests = question.visible_tests
            hidden_tests = question.hidden_tests
        return run_python_submission(
            payload.code,
            visible_tests,
            hidden_tests,
            settings.code_timeout_seconds,
        )

    @app.post("/api/questions/import")
    def import_questions(payload: QuestionImport, session: Session = Depends(db)) -> dict[str, int]:
        created = updated = 0
        for item in payload.questions:
            question = session.scalar(
                select(Question).where(Question.external_id == item.external_id)
            )
            values = item.model_dump()
            if question:
                for key, value in values.items():
                    setattr(question, key, value)
                updated += 1
            else:
                session.add(Question(**values))
                created += 1
        session.commit()
        return {"created": created, "updated": updated}

    @app.get("/api/questions/export")
    def export_questions(session: Session = Depends(db)) -> dict[str, Any]:
        questions = session.scalars(select(Question).order_by(Question.id)).all()
        return {"version": 1, "questions": [_public_question(q, reveal=True) for q in questions]}

    @app.get("/api/questions")
    def list_questions(
        category: str | None = None,
        qtype: str | None = Query(None, alias="type"),
        search: str | None = None,
        offset: int = 0,
        limit: int = Query(50, le=500),
        session: Session = Depends(db),
    ) -> dict[str, Any]:
        statement = select(Question)
        if category:
            statement = statement.where(Question.category == category)
        if qtype:
            statement = statement.where(Question.type == qtype)
        if search:
            statement = statement.where(Question.stem.contains(search))
        total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        items = session.scalars(statement.order_by(Question.id).offset(offset).limit(limit)).all()
        return {"total": total, "items": [_public_question(q, reveal=True) for q in items]}

    @app.post("/api/questions", status_code=201)
    def create_question(payload: QuestionInput, session: Session = Depends(db)) -> dict[str, Any]:
        if session.scalar(select(Question).where(Question.external_id == payload.external_id)):
            raise HTTPException(409, "external_id 已存在")
        question = Question(**payload.model_dump())
        session.add(question)
        session.commit()
        session.refresh(question)
        return _public_question(question, reveal=True)

    @app.put("/api/questions/{question_id}")
    def update_question(
        question_id: int, payload: QuestionInput, session: Session = Depends(db)
    ) -> dict[str, Any]:
        question = session.get(Question, question_id)
        if not question:
            raise HTTPException(404, "题目不存在")
        for key, value in payload.model_dump().items():
            setattr(question, key, value)
        session.commit()
        return _public_question(question, reveal=True)

    @app.delete("/api/questions/{question_id}", status_code=204)
    def delete_question(question_id: int, session: Session = Depends(db)) -> Response:
        question = session.get(Question, question_id)
        if not question:
            raise HTTPException(404, "题目不存在")
        question.enabled = False
        session.commit()
        return Response(status_code=204)

    def candidate_data(candidate: CandidateQuestion) -> dict[str, Any]:
        display_type = candidate.type
        if display_type == "choice":
            display_type = (
                "multiple"
                if isinstance(candidate.correct_answer, list) and len(candidate.correct_answer) > 1
                else "single"
            )
        return {
            "id": candidate.id,
            "parent_question_id": candidate.parent_question_id,
            "stem": candidate.stem,
            "type": display_type,
            "difficulty": candidate.difficulty,
            "domain": candidate.category,
            "options": candidate.options,
            "choices": [
                {"key": chr(65 + index), "text": text}
                for index, text in enumerate(candidate.options)
            ],
            "correct_answer": candidate.correct_answer,
            "explanation": candidate.explanation,
            "source_url": candidate.source_url,
            "evidence_title": candidate.evidence_title,
            "evidence_excerpt": candidate.evidence_excerpt,
            "status": candidate.status,
        }

    @app.post("/api/questions/{question_id}/variants", status_code=201)
    def generate_variants(
        question_id: int,
        payload: VariantRequest,
        session: Session = Depends(db),
    ) -> dict[str, Any]:
        question = session.get(Question, question_id)
        if not question:
            raise HTTPException(404, "题目不存在")
        generator = app.state.variant_generator
        if generator is None:
            if not settings.llm_api_key or not settings.llm_model:
                raise HTTPException(422, "请先配置大模型，DDG 搜索本身不需要密钥")
            generator = build_variant_generator(settings)
            app.state.variant_generator = generator
        try:
            items = generator(question, payload.count)
        except Exception as exc:
            raise HTTPException(503, str(exc)) from exc
        candidates = []
        for item in items:
            candidate = CandidateQuestion(parent_question_id=question.id, **item)
            session.add(candidate)
            candidates.append(candidate)
        session.commit()
        for candidate in candidates:
            session.refresh(candidate)
        return {"created": len(candidates), "items": [candidate_data(c) for c in candidates]}

    @app.get("/api/candidates")
    def list_candidates(session: Session = Depends(db)) -> list[dict[str, Any]]:
        candidates = session.scalars(
            select(CandidateQuestion).order_by(CandidateQuestion.id.desc())
        ).all()
        return [candidate_data(candidate) for candidate in candidates]

    @app.post("/api/candidates/{candidate_id}/approve")
    def approve_candidate(candidate_id: int, session: Session = Depends(db)) -> dict[str, Any]:
        candidate = session.get(CandidateQuestion, candidate_id)
        if not candidate:
            raise HTTPException(404, "候选题不存在")
        if candidate.status != "pending":
            raise HTTPException(409, "候选题已经审核")
        question = Question(
            external_id=f"ai-candidate-{candidate.id}",
            type=candidate.type,
            difficulty=candidate.difficulty,
            category=candidate.category,
            stem=candidate.stem,
            options=candidate.options,
            correct_answer=candidate.correct_answer,
            explanation=candidate.explanation,
            scoring_points=candidate.scoring_points,
            tags=candidate.tags,
            source_url=candidate.source_url,
            verified_at=date.today(),
            is_core=True,
            enabled=True,
        )
        session.add(question)
        candidate.status = "approved"
        candidate.reviewed_at = datetime.now(UTC)
        session.commit()
        session.refresh(question)
        return {
            "candidate": candidate_data(candidate),
            "question": _public_question(question, True),
        }

    @app.post("/api/candidates/{candidate_id}/reject")
    def reject_candidate(candidate_id: int, session: Session = Depends(db)) -> dict[str, Any]:
        candidate = session.get(CandidateQuestion, candidate_id)
        if not candidate:
            raise HTTPException(404, "候选题不存在")
        candidate.status = "rejected"
        candidate.reviewed_at = datetime.now(UTC)
        session.commit()
        return candidate_data(candidate)

    @app.post("/api/review-cards/import")
    def import_cards(payload: ReviewCardImport, session: Session = Depends(db)) -> dict[str, int]:
        session.add_all(ReviewCard(**card.model_dump()) for card in payload.cards)
        session.commit()
        return {"created": len(payload.cards)}

    @app.get("/api/review-cards")
    def list_review_cards(
        category: str | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int = Query(50, le=200),
        session: Session = Depends(db),
    ) -> dict[str, Any]:
        filters: list[Any] = [ReviewCard.enabled]
        if category:
            filters.append(ReviewCard.category == category)
        if search:
            term = f"%{search.strip().casefold()}%"
            filters.append(
                func.lower(ReviewCard.title).like(term)
                | func.lower(ReviewCard.content).like(term)
                | func.lower(cast(ReviewCard.tags, String)).like(term)
            )
        total = session.scalar(select(func.count(ReviewCard.id)).where(*filters)) or 0
        cards = session.scalars(
            select(ReviewCard)
            .where(*filters)
            .order_by(ReviewCard.category, ReviewCard.id)
            .offset(offset)
            .limit(limit)
        ).all()
        return {"total": total, "items": [_review_card_data(card) for card in cards]}

    # ---- Resume upload & parsing (P1) ----
    def _uploads_dir() -> Path:
        prefix = "sqlite:///"
        base = Path(settings.database_url.removeprefix(prefix)).resolve().parent
        uploads = base / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        return uploads

    def _resume_data(resume: Resume) -> dict[str, Any]:
        return {
            "id": resume.id,
            "filename": resume.filename,
            "status": resume.status,
            "source": resume.source,
            "error": resume.error,
            "structured": resume.structured_json,
            "job_description": resume.job_description,
            "raw_preview": resume.raw_markdown[:2000],
            "created_at": _aware(resume.created_at),
        }

    @app.post("/api/resumes", status_code=201)
    def upload_resume(
        file: UploadFile = File(...),
        job_description: str = Form(""),
        session: Session = Depends(db),
    ) -> dict[str, Any]:
        original = Path(file.filename or "resume.pdf").name
        if Path(original).suffix.lower() != ".pdf":
            raise HTTPException(422, "仅支持 PDF 简历文件")
        payload = file.file.read()
        if not payload:
            raise HTTPException(422, "上传文件为空")
        if len(payload) > 20 * 1024 * 1024:
            raise HTTPException(413, "文件超过 20MB 限制")
        dest = _uploads_dir() / f"{uuid4().hex}_{original}"
        dest.write_bytes(payload)
        resume = Resume(filename=original, job_description=job_description)
        cfg = effective_llm_config_from_session(settings, session)
        parser = app.state.resume_parser or parse_resume
        try:
            markdown, structured, source = parser(
                dest, job_description, cfg, settings.llm_timeout_seconds
            )
        except Exception as exc:
            resume.status = "failed"
            resume.error = str(exc)[:2000]
            resume.source = "markitdown"
            session.add(resume)
            session.commit()
            raise HTTPException(422, f"简历解析失败：{exc}") from exc
        resume.raw_markdown = markdown
        resume.structured_json = structured
        resume.source = source
        resume.status = "parsed"
        session.add(resume)
        session.commit()
        session.refresh(resume)
        return _resume_data(resume)

    @app.get("/api/resumes/latest")
    def resume_latest(session: Session = Depends(db)) -> dict[str, Any] | None:
        resume = session.scalar(select(Resume).order_by(Resume.id.desc()).limit(1))
        return _resume_data(resume) if resume else None

    @app.get("/api/resumes")
    def list_resumes(session: Session = Depends(db)) -> dict[str, Any]:
        resumes = session.scalars(select(Resume).order_by(Resume.id.desc()).limit(20)).all()
        return {"total": len(resumes), "items": [_resume_data(r) for r in resumes]}

    # ---- LLM provider config (GUI-managed, .env fallback) ----
    @app.get("/api/llm/provider")
    def llm_provider_get(session: Session = Depends(db)) -> dict[str, Any]:
        provider = read_provider(session)
        cfg = effective_llm_config(settings, provider)
        return {
            "display_name": cfg.display_name or cfg.model or "未配置",
            "base_url": cfg.base_url,
            "api_key": cfg.api_key,
            "model": cfg.model,
            "configured": cfg.configured,
            "active": provider is not None,
        }

    @app.put("/api/llm/provider")
    def llm_provider_put(
        payload: LlmProviderInput, session: Session = Depends(db)
    ) -> dict[str, Any]:
        provider = payload.model_dump()
        write_provider(session, provider)
        cfg = effective_llm_config(settings, provider)
        return {**provider, "configured": cfg.configured, "active": True}

    @app.delete("/api/llm/provider", status_code=204)
    def llm_provider_delete(session: Session = Depends(db)) -> Response:
        row = session.get(AppSetting, PROVIDER_SETTING_KEY)
        if row:
            session.delete(row)
            session.commit()
        return Response(status_code=204)

    # ---- Question plan: research -> confirm -> generate 50 questions (P2) ----
    def _plan_data(plan: QuestionPlan) -> dict[str, Any]:
        return {
            "id": plan.id,
            "resume_id": plan.resume_id,
            "status": plan.status,
            "total": plan.total,
            "generated_count": plan.generated_count,
            "error": plan.error,
            "plan": plan.plan_json,
            "created_at": _aware(plan.created_at),
        }

    def _start_plan_thread(plan_id: int, work: Any) -> None:
        def runner() -> None:
            try:
                work()
            except Exception as exc:  # noqa: BLE001 - persist failures for retry
                with factory() as session:
                    plan = session.get(QuestionPlan, plan_id)
                    if plan and plan.status not in {"done"}:
                        plan.status = "failed"
                        plan.error = str(exc)[:2000]
                        session.commit()

        threading.Thread(target=runner, daemon=True, name=f"plan-{plan_id}").start()

    @app.post("/api/resumes/{resume_id}/plan", status_code=201)
    def plan_create(resume_id: int, session: Session = Depends(db)) -> dict[str, Any]:
        resume = session.get(Resume, resume_id)
        if not resume:
            raise HTTPException(404, "简历不存在")
        if resume.status != "parsed":
            raise HTTPException(409, "简历尚未解析成功")
        cfg = effective_llm_config_from_session(settings, session)
        if not cfg.configured:
            raise HTTPException(422, "请先配置大模型")
        plan = QuestionPlan(resume_id=resume_id, status="pending")
        session.add(plan)
        session.commit()
        session.refresh(plan)
        plan_id = plan.id

        def work() -> None:
            structured = resume.structured_json
            job_description = resume.job_description
            research = app.state.research_fn or research_plan
            plan_json = research(
                structured, job_description, cfg, settings.llm_timeout_seconds
            )
            with factory() as session:
                row = session.get(QuestionPlan, plan_id)
                row.plan_json = plan_json
                row.status = "confirming"
                session.commit()

        _start_plan_thread(plan_id, work)
        return _plan_data(plan)

    @app.get("/api/resumes/{resume_id}/plan")
    def resume_plan_get(
        resume_id: int, session: Session = Depends(db)
    ) -> dict[str, Any]:
        plan = session.scalar(
            select(QuestionPlan)
            .where(QuestionPlan.resume_id == resume_id)
            .order_by(QuestionPlan.id.desc())
        )
        if not plan:
            raise HTTPException(404, "该简历尚未生成规划表")
        return _plan_data(plan)

    @app.get("/api/plans/{plan_id}")
    def plan_get(plan_id: int, session: Session = Depends(db)) -> dict[str, Any]:
        plan = session.get(QuestionPlan, plan_id)
        if not plan:
            raise HTTPException(404, "规划表不存在")
        return _plan_data(plan)

    @app.post("/api/plans/{plan_id}/confirm", status_code=202)
    def plan_confirm(plan_id: int, session: Session = Depends(db)) -> dict[str, Any]:
        plan = session.get(QuestionPlan, plan_id)
        if not plan:
            raise HTTPException(404, "规划表不存在")
        if plan.status != "confirming":
            raise HTTPException(409, f"规划表当前状态为 {plan.status}，无法确认")
        if not plan.plan_json.get("domains"):
            raise HTTPException(409, "规划表内容为空")
        plan.status = "generating"
        plan.generated_count = 0
        plan.error = None
        session.commit()

        def work() -> None:
            with factory() as session:
                row = session.get(QuestionPlan, plan_id)
                cfg = effective_llm_config_from_session(settings, session)
                generator = app.state.generate_fn or generate_for_plan
                generator(session, row, cfg, settings.llm_timeout_seconds)

        _start_plan_thread(plan_id, work)
        return _plan_data(plan)

    @app.post("/api/plans/{plan_id}/retry", status_code=202)
    def plan_retry(plan_id: int, session: Session = Depends(db)) -> dict[str, Any]:
        plan = session.get(QuestionPlan, plan_id)
        if not plan:
            raise HTTPException(404, "规划表不存在")
        if plan.status != "failed":
            raise HTTPException(409, f"规划表当前状态为 {plan.status}，无需重试")
        plan.status = "generating"
        session.commit()

        def work() -> None:
            with factory() as session:
                row = session.get(QuestionPlan, plan_id)
                cfg = effective_llm_config_from_session(settings, session)
                generator = app.state.generate_fn or generate_for_plan
                generator(session, row, cfg, settings.llm_timeout_seconds)

        _start_plan_thread(plan_id, work)
        return _plan_data(plan)

    # ---- 模拟面试 ----

    def _sse(event: dict[str, Any]) -> str:
        return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    def _interview_weak_areas(session: Session) -> list[str]:
        """笔试弱项：最近一次已提交正式笔试中得分最低的类别（按得分升序）。"""
        attempt = _latest_submitted_formal(session)
        if attempt is None:
            return []
        abilities = _ability_stats_for_attempt(attempt)
        return [a["name"] for a in abilities if a["answered"] >= 3][:3]

    def _latest_structured_resume(session: Session) -> Resume:
        resume = session.scalar(
            select(Resume).where(Resume.status == "parsed").order_by(Resume.id.desc())
        )
        if not resume:
            raise HTTPException(409, "请先上传并解析简历")
        return resume

    def _bank_query_fn(
        session: Session, resume_id: int
    ) -> Callable[[str, int], list[dict[str, Any]]]:
        def query(category: str, count: int = 3) -> list[dict[str, Any]]:
            questions = active_plan_questions(session)
            picked = [q for q in questions if q.category == category][: max(1, count)]
            return [
                {
                    "category": q.category,
                    "difficulty": q.difficulty,
                    "stem": q.stem[:300],
                }
                for q in picked
            ]
        return query

    @app.post("/api/interview/sessions", status_code=201)
    def interview_create(
        payload: InterviewCreate, session: Session = Depends(db)
    ) -> dict[str, Any]:
        resume = _latest_structured_resume(session)
        cfg = effective_llm_config_from_session(settings, session)
        if not cfg.configured:
            raise HTTPException(422, "请先配置大模型")
        structured = resume.structured_json or {}
        weak_areas = _interview_weak_areas(session)
        try:
            blueprint = generate_blueprint(
                structured, resume.job_description, weak_areas, cfg, settings.llm_timeout_seconds
            )
        except Exception as exc:  # noqa: BLE001 - surface a friendly message
            raise HTTPException(422, f"面试蓝图生成失败：{exc}") from exc
        row = InterviewSession(
            resume_id=resume.id,
            status="active",
            stage="opening",
            question_plan_json=blueprint,
            weak_areas=weak_areas,
            started_at=datetime.now(UTC),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _interview_session_data(row)

    def _interview_session_data(row: InterviewSession) -> dict[str, Any]:
        return {
            "id": row.id,
            "resume_id": row.resume_id,
            "status": row.status,
            "stage": row.stage,
            "current_index": row.current_index,
            "follow_up_count": row.follow_up_count,
            "blueprint": row.question_plan_json or {},
            "weak_areas": row.weak_areas or [],
            "created_at": _aware(row.created_at),
            "started_at": _aware(row.started_at) if row.started_at else None,
            "ended_at": _aware(row.ended_at) if row.ended_at else None,
        }

    @app.get("/api/interview/sessions")
    def interview_list(session: Session = Depends(db)) -> list[dict[str, Any]]:
        rows = session.scalars(
            select(InterviewSession).order_by(InterviewSession.id.desc()).limit(50)
        )
        return [_interview_session_data(r) for r in rows]

    @app.get("/api/interview/sessions/{session_id}")
    def interview_detail(
        session_id: int, session: Session = Depends(db)
    ) -> dict[str, Any]:
        row = session.get(InterviewSession, session_id)
        if not row:
            raise HTTPException(404, "面试会话不存在")
        data = _interview_session_data(row)
        data["messages"] = [
            {"id": m.id, "role": m.role, "content": m.content, "created_at": _aware(m.created_at)}
            for m in row.messages
        ]
        return data

    @app.get("/api/interview/sessions/{session_id}/report")
    def interview_report_get(
        session_id: int, session: Session = Depends(db)
    ) -> dict[str, Any]:
        row = session.get(InterviewSession, session_id)
        if not row:
            raise HTTPException(404, "面试会话不存在")
        if not row.report:
            raise HTTPException(404, "报告尚未生成")
        return {
            "id": row.report.id,
            "session_id": row.id,
            "summary_text": row.report.summary_text,
            "score": row.report.score,
            "questions": row.report.questions_json or [],
            "created_at": _aware(row.report.created_at),
        }

    @app.post("/api/interview/sessions/{session_id}/messages")
    def interview_message(
        session_id: int,
        payload: InterviewMessageIn,
        session: Session = Depends(db),
    ) -> StreamingResponse:
        row = session.get(InterviewSession, session_id)
        if not row:
            raise HTTPException(404, "面试会话不存在")
        if row.status != "active":
            raise HTTPException(409, "面试已结束")
        cfg = effective_llm_config_from_session(settings, session)
        if not cfg.configured:
            raise HTTPException(422, "请先配置大模型")
        session.add(
            InterviewMessage(session_id=row.id, role="user", content=payload.content.strip())
        )
        session.commit()
        resume = session.get(Resume, row.resume_id)
        structured = resume.structured_json if resume else {}
        bank_fn = _bank_query_fn(session, row.resume_id)

        def event_stream() -> Any:
            yield _sse({"type": "thinking"})
            for event in run_turn_events(
                session,
                row,
                structured,
                resume.job_description if resume else "",
                cfg,
                bank_fn,
            ):
                yield _sse(event)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.post("/api/interview/sessions/{session_id}/end", status_code=202)
    def interview_end(session_id: int, session: Session = Depends(db)) -> dict[str, Any]:
        row = session.get(InterviewSession, session_id)
        if not row:
            raise HTTPException(404, "面试会话不存在")
        if row.status != "active":
            return _interview_session_data(row)
        cfg = effective_llm_config_from_session(settings, session)
        if not cfg.configured:
            raise HTTPException(422, "请先配置大模型")
        resume = session.get(Resume, row.resume_id)
        structured = resume.structured_json if resume else {}
        jd = resume.job_description if resume else ""
        row.stage = "closing"
        session.commit()

        def work() -> None:
            with factory() as thread_session:
                r = thread_session.get(InterviewSession, session_id)
                if not r or r.report:
                    return
                try:
                    report = generate_report(
                        structured,
                        jd,
                        [
                            {"role": m.role, "content": m.content}
                            for m in r.messages
                        ],
                        r.question_plan_json or {},
                        cfg,
                        settings.llm_timeout_seconds,
                    )
                    thread_session.add(
                        InterviewReport(
                            session_id=r.id,
                            summary_text=str(report.get("summary") or ""),
                            score=float(report.get("overall_score") or 0),
                            questions_json=report.get("questions") or [],
                        )
                    )
                    r.status = "ended"
                    r.stage = "closing"
                    r.ended_at = datetime.now(UTC)
                    thread_session.commit()
                except Exception:  # noqa: BLE001
                    thread_session.rollback()
                    r.status = "ended"
                    r.stage = "closing"
                    r.ended_at = datetime.now(UTC)
                    thread_session.commit()

        threading.Thread(target=work, daemon=True, name=f"interview-report-{session_id}").start()
        return _interview_session_data(row)

    def create_attempt(payload: AttemptCreate, session: Session) -> dict[str, Any]:
        if payload.mode != "formal":
            raise HTTPException(
                422,
                "该练习模式已下线，请使用正式笔试（50 题）或进入模拟面试",
            )
        for previous in session.scalars(
            select(Attempt).where(Attempt.status.in_(["reviewing", "in_progress"]))
        ):
            previous.status = "abandoned"
        questions = active_plan_questions(session)
        if len(questions) < EXAM_QUESTION_COUNT:
            raise HTTPException(
                409,
                "当前题库不足 50 题，请先在初始化流程完成规划表生成（或重试待补领域）",
            )
        random.shuffle(questions)
        attempt = Attempt(mode="formal", duration_minutes=EXAM_DURATION_MINUTES)
        session.add(attempt)
        session.flush()
        for position, question in enumerate(questions[:EXAM_QUESTION_COUNT], 1):
            session.add(
                AttemptQuestion(
                    attempt_id=attempt.id,
                    question_id=question.id,
                    position=position,
                    weight=2.0,
                )
            )
        session.commit()
        attempt = load_attempt(session, attempt.id)
        cards = _review_cards_for_attempt(session, attempt)
        return _attempt_data(attempt, cards)

    @app.post("/api/attempts", status_code=201)
    def attempts_create(payload: AttemptCreate, session: Session = Depends(db)) -> dict[str, Any]:
        return create_attempt(payload, session)

    @app.post("/api/exams", status_code=201, include_in_schema=False)
    def exams_create(payload: AttemptCreate, session: Session = Depends(db)) -> dict[str, Any]:
        return create_attempt(payload, session)

    def active_attempt(session: Session) -> dict[str, Any] | None:
        attempt = session.scalar(
            select(Attempt)
            .where(Attempt.status.in_(["reviewing", "in_progress"]))
            .order_by(Attempt.id.desc())
        )
        if not attempt:
            return None
        attempt = load_attempt(session, attempt.id)
        if attempt.status == "in_progress" and _deadline_passed(attempt):
            submit_attempt(attempt.id, session)
            return None
        return _attempt_data(attempt, _review_cards_for_attempt(session, attempt))

    @app.get("/api/attempts/active")
    def attempts_active(session: Session = Depends(db)) -> dict[str, Any] | None:
        return active_attempt(session)

    @app.get("/api/exams/active", include_in_schema=False)
    def exams_active(session: Session = Depends(db)) -> dict[str, Any] | None:
        return active_attempt(session)

    @app.get("/api/attempts/{attempt_id}")
    def get_attempt(attempt_id: int, session: Session = Depends(db)) -> dict[str, Any]:
        attempt = load_attempt(session, attempt_id)
        if attempt.status == "in_progress" and _deadline_passed(attempt):
            return submit_attempt(attempt_id, session)
        cards = _review_cards_for_attempt(session, attempt) if attempt.status == "reviewing" else []
        return _attempt_data(attempt, cards, reveal=attempt.status == "submitted")

    def confirm(attempt_id: int, session: Session) -> dict[str, Any]:
        attempt = load_attempt(session, attempt_id)
        if attempt.status != "reviewing":
            raise HTTPException(409, "考试已经开始或结束")
        now = datetime.now(UTC)
        attempt.status = "in_progress"
        attempt.started_at = now
        attempt.deadline_at = now + timedelta(minutes=attempt.duration_minutes)
        session.commit()
        return _attempt_data(attempt)

    @app.post("/api/attempts/{attempt_id}/review-confirm")
    def review_confirm(attempt_id: int, session: Session = Depends(db)) -> dict[str, Any]:
        return confirm(attempt_id, session)

    @app.post("/api/exams/{attempt_id}/confirm-review", include_in_schema=False)
    def confirm_alias(attempt_id: int, session: Session = Depends(db)) -> dict[str, Any]:
        return confirm(attempt_id, session)

    def save_answer(
        attempt_id: int, question_id: int, payload: AnswerInput, session: Session
    ) -> dict[str, Any]:
        attempt = load_attempt(session, attempt_id)
        if attempt.status != "in_progress":
            raise HTTPException(409, "考试未开始或已经结束")
        if _deadline_passed(attempt):
            submit_attempt(attempt_id, session)
            raise HTTPException(409, "考试已超时并自动交卷")
        question_ids = {item.question_id for item in attempt.questions}
        if question_id not in question_ids:
            raise HTTPException(404, "该题不属于本次考试")
        answer = session.scalar(
            select(Answer).where(Answer.attempt_id == attempt_id, Answer.question_id == question_id)
        )
        if not answer:
            answer = Answer(attempt_id=attempt_id, question_id=question_id)
            session.add(answer)
        answer.answer = payload.answer
        answer.flagged = payload.flagged
        answer.elapsed_seconds = payload.elapsed_seconds
        question = session.get(Question, question_id)
        if question and question.type == "choice":
            answer.is_correct = payload.answer == question.correct_answer
        session.commit()
        session.refresh(answer)
        return {
            "id": answer.id,
            "question_id": question_id,
            "saved": True,
            "updated_at": _aware(answer.updated_at),
        }

    @app.put("/api/attempts/{attempt_id}/answers/{question_id}")
    def attempts_save(
        attempt_id: int, question_id: int, payload: AnswerInput, session: Session = Depends(db)
    ) -> dict[str, Any]:
        return save_answer(attempt_id, question_id, payload, session)

    @app.put("/api/exams/{attempt_id}/answers/{question_id}", include_in_schema=False)
    def exams_save(
        attempt_id: int, question_id: int, payload: AnswerInput, session: Session = Depends(db)
    ) -> dict[str, Any]:
        return save_answer(attempt_id, question_id, payload, session)

    def checkpoint(attempt_id: int, number: int, session: Session) -> dict[str, Any]:
        if number not in {1, 2, 3, 4}:
            raise HTTPException(422, "检查点必须为 1 到 4")
        attempt = load_attempt(session, attempt_id)
        if attempt.status != "in_progress":
            raise HTTPException(409, "考试未进行")
        item = session.scalar(
            select(Checkpoint).where(
                Checkpoint.attempt_id == attempt_id, Checkpoint.number == number
            )
        )
        if not item:
            item = Checkpoint(attempt_id=attempt_id, number=number, through_position=number * 25)
            session.add(item)
            session.commit()
        start_position = (number - 1) * 25
        segment = [
            attempt_question
            for attempt_question in attempt.questions
            if start_position < attempt_question.position <= number * 25
        ]
        answer_by_question = {answer.question_id: answer for answer in attempt.answers}
        objective = [
            answer_by_question[item.question_id]
            for item in segment
            if item.question.type == "choice" and item.question_id in answer_by_question
        ]
        weak_categories = Counter(
            item.question.category
            for item in segment
            if item.question_id in answer_by_question
            and answer_by_question[item.question_id].is_correct is False
        )
        return {
            "number": item.number,
            "through_position": item.through_position,
            "completed_at": _aware(item.completed_at),
            "answered": sum(item.question_id in answer_by_question for item in segment),
            "objective_correct": sum(answer.is_correct is True for answer in objective),
            "objective_total": len(objective),
            "weak_categories": [name for name, _ in weak_categories.most_common(3)],
        }

    @app.post("/api/attempts/{attempt_id}/checkpoints/{number}")
    def attempts_checkpoint(
        attempt_id: int, number: int, session: Session = Depends(db)
    ) -> dict[str, Any]:
        return checkpoint(attempt_id, number, session)

    @app.post("/api/exams/{attempt_id}/checkpoints/{number}", include_in_schema=False)
    def exams_checkpoint(
        attempt_id: int, number: int, session: Session = Depends(db)
    ) -> dict[str, Any]:
        return checkpoint(attempt_id, number, session)

    def submit_attempt(attempt_id: int, session: Session) -> dict[str, Any]:
        attempt = load_attempt(session, attempt_id)
        if attempt.status == "submitted":
            return _attempt_data(attempt, reveal=True)
        if attempt.status != "in_progress":
            raise HTTPException(409, "考试未开始")
        attempt.status = "submitted"
        attempt.submitted_at = datetime.now(UTC)
        for answer in attempt.answers:
            question = session.get(Question, answer.question_id)
            if question and question.type == "choice" and answer.is_correct is not None:
                mastery = session.get(QuestionMastery, question.id)
                if not mastery:
                    mastery = QuestionMastery(
                        question_id=question.id,
                        streak=0,
                        interval_days=0,
                        status="new",
                    )
                    session.add(mastery)
                mastery.last_result = answer.is_correct
                if answer.is_correct:
                    mastery.streak += 1
                    mastery.interval_days = 7 if mastery.streak >= 2 else 3
                    mastery.status = "mastered" if mastery.streak >= 3 else "learning"
                    mastery.due_at = date.today() + timedelta(days=mastery.interval_days)
                else:
                    mastery.streak = 0
                    mastery.interval_days = 0
                    mastery.status = "weak"
                    mastery.due_at = date.today()
            if (
                question
                and question.type in SUBJECTIVE_TYPES
                and answer.answer not in (None, "", [])
            ):
                if not session.scalar(
                    select(GradingTask).where(GradingTask.answer_id == answer.id)
                ):
                    session.add(GradingTask(answer_id=answer.id))
        session.commit()
        return _attempt_data(load_attempt(session, attempt_id), reveal=True)

    @app.post("/api/attempts/{attempt_id}/submit")
    def attempts_submit(attempt_id: int, session: Session = Depends(db)) -> dict[str, Any]:
        return submit_attempt(attempt_id, session)

    @app.post("/api/exams/{attempt_id}/submit", include_in_schema=False)
    def exams_submit(attempt_id: int, session: Session = Depends(db)) -> dict[str, Any]:
        return submit_attempt(attempt_id, session)

    @app.get("/api/attempts/{attempt_id}/review")
    def review(attempt_id: int, session: Session = Depends(db)) -> dict[str, Any]:
        attempt = load_attempt(session, attempt_id)
        if attempt.status != "submitted":
            raise HTTPException(409, "交卷后才能复盘")
        return _attempt_data(attempt, reveal=True)

    @app.get("/api/grading/tasks")
    def grading_tasks(
        task_status: str | None = Query(None, alias="status"), session: Session = Depends(db)
    ) -> dict[str, Any]:
        statement = select(GradingTask).order_by(GradingTask.id)
        if task_status:
            statement = statement.where(GradingTask.status == task_status)
        tasks = session.scalars(statement).all()
        return {
            "total": len(tasks),
            "items": [
                {
                    "id": t.id,
                    "answer_id": t.answer_id,
                    "status": t.status,
                    "error": t.error,
                    "attempts": t.attempts,
                }
                for t in tasks
            ],
        }

    def transition_task(
        task_id: int, target: str, session: Session, error: str | None = None
    ) -> dict[str, Any]:
        task = session.get(GradingTask, task_id)
        if not task:
            raise HTTPException(404, "评分任务不存在")
        task.status = target
        task.error = error
        if target == "grading":
            task.attempts += 1
        session.commit()
        return {
            "id": task.id,
            "answer_id": task.answer_id,
            "status": task.status,
            "error": task.error,
            "attempts": task.attempts,
        }

    @app.post("/api/grading/tasks/{task_id}/claim")
    def claim(task_id: int, session: Session = Depends(db)) -> dict[str, Any]:
        return transition_task(task_id, "grading", session)

    @app.post("/api/grading/tasks/{task_id}/fail")
    def fail(task_id: int, payload: FailureInput, session: Session = Depends(db)) -> dict[str, Any]:
        return transition_task(task_id, "failed", session, payload.error)

    @app.post("/api/grading/tasks/{task_id}/retry")
    def retry(task_id: int, session: Session = Depends(db)) -> dict[str, Any]:
        return transition_task(task_id, "pending", session)

    @app.post("/api/grading/tasks/{task_id}/complete")
    def complete_grading(
        task_id: int,
        payload: GradingResultInput,
        session: Session = Depends(db),
    ) -> dict[str, Any]:
        task = session.get(GradingTask, task_id)
        if not task:
            raise HTTPException(404, "评分任务不存在")
        version = GradingVersion(task_id=task.id, **payload.model_dump())
        session.add(version)
        task.status = "completed"
        task.error = None
        session.commit()
        session.refresh(version)
        return {
            "id": task.id,
            "answer_id": task.answer_id,
            "status": task.status,
            "version": _grading_data(version),
        }

    @app.get("/api/grading/tasks/{task_id}/versions")
    def grading_versions(task_id: int, session: Session = Depends(db)) -> dict[str, Any]:
        task = session.scalar(
            select(GradingTask)
            .where(GradingTask.id == task_id)
            .options(selectinload(GradingTask.versions))
        )
        if not task:
            raise HTTPException(404, "评分任务不存在")
        return {"items": [_grading_data(item) for item in task.versions]}

    @app.post("/api/attempts/{attempt_id}/grades/{question_id}/override")
    def override_grade(
        attempt_id: int,
        question_id: int,
        payload: ScoreOverrideInput,
        session: Session = Depends(db),
    ) -> dict[str, Any]:
        answer = session.scalar(
            select(Answer).where(
                Answer.attempt_id == attempt_id,
                Answer.question_id == question_id,
            )
        )
        if not answer:
            raise HTTPException(404, "答案不存在")
        task = session.scalar(
            select(GradingTask)
            .where(GradingTask.answer_id == answer.id)
            .options(selectinload(GradingTask.versions))
        )
        if not task:
            task = GradingTask(answer_id=answer.id, status="completed")
            session.add(task)
            session.flush()
        previous = task.versions[-1] if task.versions else None
        version = GradingVersion(
            task_id=task.id,
            score=payload.score,
            max_score=previous.max_score if previous else 10,
            matched_points=previous.matched_points if previous else [],
            missing_points=previous.missing_points if previous else [],
            incorrect_claims=previous.incorrect_claims if previous else [],
            improved_answer=previous.improved_answer if previous else str(answer.answer or ""),
            follow_up=previous.follow_up if previous else "",
            confidence=1.0,
            source="manual",
            reason=payload.reason,
        )
        session.add(version)
        task.status = "completed"
        session.commit()
        session.refresh(version)
        return _grading_data(version)

    @app.post("/api/grading/run", status_code=202)
    def grading_run(
        background_tasks: BackgroundTasks,
        session: Session = Depends(db),
    ) -> dict[str, Any]:
        count = (
            session.scalar(
                select(func.count()).select_from(GradingTask).where(GradingTask.status == "pending")
            )
            or 0
        )
        provider = app.state.grade_provider
        if provider is None:
            if not settings.llm_api_key or not settings.llm_model:
                raise HTTPException(422, "请先在 .env 配置 LLM_API_KEY 和 LLM_MODEL")
            provider = build_openai_grade_provider(settings)
            app.state.grade_provider = provider
        background_tasks.add_task(
            run_pending_grading,
            factory,
            provider,
            app.state.grading_stop_event,
            settings.llm_max_concurrency,
            settings.llm_max_batch_size,
        )
        return {"accepted": True, "pending": count, "message": "已开始读取待评分任务"}

    @app.post("/api/grading/stop", status_code=202)
    def grading_stop() -> dict[str, Any]:
        app.state.grading_stop_event.set()
        return {"accepted": True, "message": "停止信号已发送"}

    @app.post("/api/grading/requeue")
    def grading_requeue(
        attempt_id: int,
        include_completed: bool = False,
        session: Session = Depends(db),
    ) -> dict[str, int]:
        statuses = ["failed", "completed"] if include_completed else ["failed"]
        tasks = list(
            session.scalars(
                select(GradingTask)
                .join(Answer)
                .where(
                    Answer.attempt_id == attempt_id,
                    GradingTask.status.in_(statuses),
                )
            )
        )
        for task in tasks:
            task.status = "pending"
            task.error = None
        session.commit()
        return {"requeued": len(tasks)}

    frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend_dist.exists():
        assets = frontend_dist / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def frontend_spa(full_path: str) -> FileResponse:
            requested = (frontend_dist / full_path).resolve()
            if requested.is_file() and frontend_dist.resolve() in requested.parents:
                return FileResponse(requested)
            return FileResponse(frontend_dist / "index.html")

    return app


app = create_app()
