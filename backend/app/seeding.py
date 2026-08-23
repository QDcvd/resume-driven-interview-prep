from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Question, ReviewCard
from .schemas import QuestionInput, ReviewCardInput


def _read_json_files(content_dir: Path, pattern: str) -> list[Any]:
    items: list[Any] = []
    for path in sorted(content_dir.glob(pattern)):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            items.extend(payload)
        elif isinstance(payload, dict):
            key = "questions" if "question" in pattern else "cards"
            items.extend(payload.get(key, []))
    return items


def seed_content_if_empty(session: Session, content_dir: Path) -> dict[str, int]:
    seeded = {"questions": 0, "cards": 0}
    # 启动时只补充缺失内容，保留用户已经在 SQLite 中手动修订的数据。
    existing_by_external_id = {
        question.external_id: question
        for question in session.scalars(select(Question))
    }
    handled_questions: set[str] = set()
    for raw in _read_json_files(content_dir, "*question*.json"):
        item = QuestionInput.model_validate(raw)
        if item.external_id in handled_questions:
            continue
        if existing_by_external_id.get(item.external_id) is None:
            session.add(Question(**item.model_dump()))
            seeded["questions"] += 1
        handled_questions.add(item.external_id)
    # 卡片同样只按标题补充，避免服务重启覆盖用户编辑。
    existing_by_title = {
        card.title: card for card in session.scalars(select(ReviewCard))
    }
    handled: set[str] = set()
    for raw in _read_json_files(content_dir, "*review*.json"):
        card = ReviewCardInput.model_validate(raw)
        if card.title in handled:
            continue
        if existing_by_title.get(card.title) is None:
            session.add(ReviewCard(**card.model_dump()))
            seeded["cards"] += 1
        handled.add(card.title)
    session.commit()
    return seeded
