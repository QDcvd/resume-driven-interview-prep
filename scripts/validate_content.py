"""Validate the curated question bank before it is imported into SQLite."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from backend.app.schemas import QuestionInput, ReviewCardInput
from backend.app.services import CATEGORY_QUOTAS, TYPE_DIFFICULTY_QUOTAS

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "content"
MIN_CORE_QUESTIONS = 450
MIN_REVIEW_CARDS = 75


def read_items(pattern: str, key: str) -> list[dict]:
    items = []
    for path in sorted(CONTENT.glob(pattern)):
        payload = json.loads(path.read_text(encoding="utf-8"))
        items.extend(payload if isinstance(payload, list) else payload.get(key, []))
    return items


def main() -> None:
    all_questions = [
        QuestionInput.model_validate(item)
        for item in read_items("*question*.json", "questions")
    ]
    questions = [item for item in all_questions if item.is_core]
    cards = [ReviewCardInput.model_validate(item) for item in read_items("*review*.json", "cards")]
    if len(questions) < MIN_CORE_QUESTIONS:
        raise SystemExit(f"核心题库不足：{len(questions)} / {MIN_CORE_QUESTIONS}")
    external_ids = [item.external_id for item in all_questions]
    stems = [" ".join(item.stem.lower().split()) for item in all_questions]
    if len(external_ids) != len(set(external_ids)):
        raise SystemExit("external_id 存在重复")
    duplicate_stems = [stem for stem, count in Counter(stems).items() if count > 1]
    if duplicate_stems:
        raise SystemExit(f"题干重复：{duplicate_stems[:5]}")
    if any(not item.source_url for item in all_questions):
        raise SystemExit("存在没有来源的题目")
    if any("example.com" in item.source_url or "占位" in item.stem for item in all_questions):
        raise SystemExit("存在占位题或占位来源")
    if any(item.type == "choice" and len(item.options) < 4 for item in questions):
        raise SystemExit("选择题必须至少有四个选项")
    if any(
        item.type == "choice" and item.correct_answer not in {"A", "B", "C", "D"}
        for item in questions
    ):
        raise SystemExit("选择题 correct_answer 必须是 A/B/C/D")
    answer_counts = Counter(
        item.correct_answer for item in questions if item.type == "choice"
    )
    choice_total = sum(answer_counts.values())
    if any(answer_counts[letter] < choice_total * 0.1 for letter in "ABCD") or any(
        answer_counts[letter] > choice_total * 0.4 for letter in "ABCD"
    ):
        raise SystemExit(f"选择题答案位置过于集中：{answer_counts}")
    if any(item.type != "choice" and not item.scoring_points for item in questions):
        raise SystemExit("主观题必须提供 scoring_points")
    if any(
        item.type == "code" and (not item.visible_tests or not item.hidden_tests)
        for item in all_questions
    ):
        raise SystemExit("代码题必须同时提供示例测试与隐藏测试")
    type_counts = Counter(item.type for item in questions)
    difficulty_counts = Counter(item.difficulty for item in questions)
    if len(cards) < MIN_REVIEW_CARDS:
        raise SystemExit(f"复习卡不足：{len(cards)} / {MIN_REVIEW_CARDS}")
    card_categories = {card.category for card in cards}
    missing_card_categories = set(CATEGORY_QUOTAS) - card_categories
    if missing_card_categories:
        raise SystemExit(f"复习卡未覆盖领域：{sorted(missing_card_categories)}")
    slot_counts = Counter((item.type, item.difficulty) for item in questions)
    missing_slots = {
        (qtype, difficulty): needed - slot_counts[(qtype, difficulty)]
        for qtype, difficulties in TYPE_DIFFICULTY_QUOTAS.items()
        for difficulty, needed in difficulties.items()
        if slot_counts[(qtype, difficulty)] < needed
    }
    category_counts = Counter(item.category for item in questions)
    missing_categories = {
        category: needed - category_counts[category]
        for category, needed in CATEGORY_QUOTAS.items()
        if category_counts[category] < needed
    }
    if missing_slots or missing_categories:
        raise SystemExit(f"无法组成正式卷：slots={missing_slots}, categories={missing_categories}")
    print(
        json.dumps(
            {
                "questions": len(questions),
                "supplemental_questions": len(all_questions) - len(questions),
                "cards": len(cards),
                "types": type_counts,
                "difficulties": difficulty_counts,
                "categories": category_counts,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
