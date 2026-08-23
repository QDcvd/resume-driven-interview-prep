import random
from collections import Counter

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Attempt, AttemptQuestion, Question, QuestionPlan

EXAM_QUESTION_COUNT = 50
EXAM_DURATION_MINUTES = 60


def active_plan_questions(session: Session) -> list[Question]:
    """The active 50-question objective bank: the latest confirmed plan's
    generated questions. Empty when no plan has finished generating yet."""
    plan = session.scalar(
        select(QuestionPlan)
        .where(QuestionPlan.status == "done")
        .order_by(QuestionPlan.id.desc())
    )
    if not plan:
        return []
    prefix = f"ai-plan-{plan.id}-%"
    return list(
        session.scalars(
            select(Question)
            .where(Question.external_id.like(prefix))
            .order_by(Question.id)
        )
    )


TYPE_DIFFICULTY_QUOTAS = {
    "choice": {"basic": 21, "practical": 35, "deep": 14},
    "short_answer": {"basic": 6, "practical": 10, "deep": 4},
    "project": {"basic": 2, "practical": 4, "deep": 2},
    "system_design": {"basic": 1, "practical": 1, "deep": 0},
}
CATEGORY_QUOTAS = {
    "php": 35,
    "frontend": 15,
    "database": 12,
    "redis_async": 8,
    "engineering": 10,
    "algorithms": 10,
    "projects": 10,
}
TYPE_WEIGHTS = {
    "choice": 40 / 70,
    "short_answer": 25 / 20,
    "project": 20 / 8,
    "system_design": 15 / 2,
}


def _recent_question_ids(session: Session, limit: int) -> set[int]:
    attempt_ids = list(
        session.scalars(
            select(Attempt.id)
            .where(Attempt.status == "submitted")
            .order_by(Attempt.submitted_at.desc())
            .limit(limit)
        )
    )
    if not attempt_ids:
        return set()
    return set(
        session.scalars(
            select(AttemptQuestion.question_id).where(AttemptQuestion.attempt_id.in_(attempt_ids))
        )
    )


def _select_pool(session: Session, excluded: set[int]) -> list[Question]:
    statement = select(Question).where(Question.enabled, Question.is_core)
    if excluded:
        statement = statement.where(Question.id.not_in(excluded))
    return list(session.scalars(statement))


def _try_select(pool: list[Question]) -> list[Question] | None:
    available = Counter((q.type, q.difficulty) for q in pool)
    if any(
        available[(qtype, difficulty)] < needed
        for qtype, difficulties in TYPE_DIFFICULTY_QUOTAS.items()
        for difficulty, needed in difficulties.items()
    ):
        return None

    # Randomized constrained greedy. Each accepted result is validated against all quotas;
    # retries handle pools where a scarce category/slot intersection must be chosen first.
    slots = [
        (qtype, difficulty)
        for qtype, difficulties in TYPE_DIFFICULTY_QUOTAS.items()
        for difficulty, needed in difficulties.items()
        for _ in range(needed)
    ]
    for _ in range(500):
        remaining = Counter(CATEGORY_QUOTAS)
        selected = []
        random.shuffle(slots)
        unused = set(q.id for q in pool)
        for qtype, difficulty in slots:
            candidates = [
                q
                for q in pool
                if q.id in unused
                and q.type == qtype
                and q.difficulty == difficulty
                and remaining[q.category] > 0
            ]
            if not candidates:
                break
            max_need = max(remaining[q.category] for q in candidates)
            candidate = random.choice([q for q in candidates if remaining[q.category] == max_need])
            selected.append(candidate)
            unused.remove(candidate.id)
            remaining[candidate.category] -= 1
        if len(selected) == 100 and not any(remaining.values()):
            break
    else:
        return None

    random.shuffle(selected)
    # System design questions are intentionally separated across checkpoints 2 and 4.
    systems = [q for q in selected if q.type == "system_design"]
    others = [q for q in selected if q.type != "system_design"]
    random.shuffle(others)
    result = others[:49] + systems[:1] + others[49:99] + systems[1:]
    return result


def generate_formal_questions(session: Session) -> list[Question]:
    # Prefer no repeats from the last two submitted exams. If the curated pool cannot
    # satisfy every hard quota, relax one exam at a time rather than silently changing
    # the requested 70/20/8/2 and 30/50/20 composition.
    for recent_count in (2, 1, 0):
        selected = _try_select(_select_pool(session, _recent_question_ids(session, recent_count)))
        if selected:
            return selected
    raise HTTPException(
        409,
        detail={
            "message": "题库不足，无法同时满足题型、难度和领域配额",
            "required": {
                "types_and_difficulties": TYPE_DIFFICULTY_QUOTAS,
                "categories": CATEGORY_QUOTAS,
            },
        },
    )
