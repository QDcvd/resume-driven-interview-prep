from __future__ import annotations

import json
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from .config import Settings
from .models import Answer, GradingTask, GradingVersion
from .schemas import GradingResultInput


@dataclass(frozen=True)
class GradingPrompt:
    question: str
    rubric: list[str]
    answer_text: str
    max_score: float = 10.0


GradeProvider = Callable[[GradingPrompt], dict[str, Any]]


def build_openai_grade_provider(settings: Settings) -> GradeProvider:
    client = OpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url or None,
        timeout=settings.llm_timeout_seconds,
    )

    def grade(prompt: GradingPrompt) -> dict[str, Any]:
        user_payload = {
            "question": prompt.question,
            "rubric": prompt.rubric,
            "candidate_answer": prompt.answer_text,
            "max_score": prompt.max_score,
        }
        completion = client.chat.completions.create(
            model=settings.llm_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是严谨的技术面试评分员。仅依据题目、评分点和候选人答案评分。"
                        "返回 JSON，字段必须包含 score,max_score,matched_points,missing_points,"
                        "incorrect_claims,improved_answer,follow_up,confidence。"
                    ),
                },
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
        )
        content = completion.choices[0].message.content or "{}"
        return GradingResultInput.model_validate_json(content).model_dump()

    return grade


def _grade_task(
    task_id: int,
    factory: sessionmaker[Session],
    provider: GradeProvider,
    stop_event: threading.Event,
) -> None:
    if stop_event.is_set():
        return
    with factory() as session:
        task = session.scalar(
            select(GradingTask)
            .where(GradingTask.id == task_id)
            .options(selectinload(GradingTask.answer).selectinload(Answer.question))
        )
        if not task or task.status != "pending":
            return
        task.status = "grading"
        task.attempts += 1
        session.commit()
        answer = task.answer
        prompt = GradingPrompt(
            question=answer.question.stem,
            rubric=answer.question.scoring_points,
            answer_text=str(answer.answer or ""),
        )
    try:
        result = GradingResultInput.model_validate(provider(prompt))
        if stop_event.is_set():
            with factory() as session:
                stopped = session.get(GradingTask, task_id)
                if stopped:
                    stopped.status = "pending"
                    session.commit()
            return
        with factory() as session:
            task = session.get(GradingTask, task_id)
            if not task:
                return
            session.add(GradingVersion(task_id=task_id, **result.model_dump()))
            task.status = "completed"
            task.error = None
            session.commit()
    except Exception as exc:  # provider failures are persisted for explicit retry
        with factory() as session:
            failed = session.get(GradingTask, task_id)
            if failed:
                failed.status = "failed"
                failed.error = str(exc)[:2_000]
                session.commit()


def run_pending_grading(
    factory: sessionmaker[Session],
    provider: GradeProvider,
    stop_event: threading.Event,
    max_workers: int,
    max_tasks: int,
) -> None:
    stop_event.clear()
    with factory() as session:
        task_ids = list(
            session.scalars(
                select(GradingTask.id)
                .where(GradingTask.status == "pending")
                .order_by(GradingTask.id)
                .limit(max_tasks)
            )
        )
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ai-grading") as executor:
        futures = [
            executor.submit(_grade_task, task_id, factory, provider, stop_event)
            for task_id in task_ids
        ]
        for future in as_completed(futures):
            future.result()
