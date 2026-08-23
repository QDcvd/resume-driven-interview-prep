"""Generate the 50 objective questions from a confirmed plan.

Per-domain chunks: search evidence for the domain, have the LLM write the
domain's share of questions grounded in that evidence, verify every question
is backed by a real evidence URL, then persist. A failing domain is retried a
couple of times and otherwise reported as "待补" so the user can re-run it.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .llm_provider import LlmConfig, build_openai_client
from .models import Question, QuestionPlan
from .search import web_search

MAX_DOMAIN_RETRIES = 2
OPTION_KEYS = ("A", "B", "C", "D")

# Injectable generation signature: (session, plan, cfg, timeout) -> result dict.
GenerateFn = Callable[[Session, QuestionPlan, LlmConfig, float], dict[str, Any]]

GENERATION_SYSTEM_PROMPT = (
    "你是笔试出题官。为给定技术领域生成指定数量的【单选客观题】（4 个选项、1 个正确答案）。\n"
    "必须严格依据提供的检索证据出题；每题 source_url 必须引用证据列表中存在的一个 URL，"
    "且题目内容必须被该来源支持。禁止使用证据之外的事实。\n"
    "输出 JSON：{\"questions\": [{\"stem\": \"题干\", \"options\": [\"A\",\"B\",\"C\",\"D\"], "
    "\"correct_answer\": \"A\", \"explanation\": \"解析\", "
    "\"difficulty\": \"basic|practical|deep\", "
    "\"source_url\": \"证据URL\", \"scoring_points\": [\"要点1\",\"要点2\"]}]}\n"
    "难度分布必须严格符合要求的 basic/practical/deep 数量。"
)


def _valid_choice(item: dict[str, Any]) -> bool:
    stem = str(item.get("stem", "")).strip()
    options = item.get("options")
    correct = str(item.get("correct_answer", "")).strip().upper()
    if not stem or not isinstance(options, list) or len(options) != 4:
        return False
    if correct not in OPTION_KEYS:
        return False
    if any(not isinstance(o, str) or not o.strip() for o in options):
        return False
    return True


def generate_domain_questions(
    domain: str,
    count: int,
    difficulty: dict[str, int],
    cfg: LlmConfig,
    timeout: float,
) -> list[dict[str, Any]]:
    """One chunk: search + LLM generation + evidence verification."""
    evidence = web_search(f"{domain} 面试题", max_results=8, cfg=cfg)
    if not evidence:
        raise ValueError(f"领域 {domain} 未检索到可用证据")
    evidence_by_url = {item["url"]: item for item in evidence}

    client = build_openai_client(cfg, timeout)
    user_payload = {
        "domain": domain,
        "count": count,
        "difficulty_distribution": difficulty,
        "evidence": evidence,
    }
    completion = client.chat.completions.create(
        model=cfg.model,
        temperature=0.4,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": GENERATION_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
    )
    payload = json.loads(completion.choices[0].message.content or "{}")
    items = payload.get("questions", [])
    if not isinstance(items, list):
        items = []

    valid: list[dict[str, Any]] = []
    for item in items[:count]:
        if not _valid_choice(item):
            continue
        source_url = str(item.get("source_url", ""))
        source = evidence_by_url.get(source_url)
        if source is None:
            continue
        item["source_url"] = source_url
        item["evidence_title"] = source["title"]
        valid.append(item)
    if not valid:
        raise ValueError(f"领域 {domain} 生成结果无法由检索来源核验")
    return valid


def _persist_question(
    session: Session, plan: QuestionPlan, domain: str, index: int, item: dict[str, Any]
) -> None:
    explanation = str(item.get("explanation", "")).strip()
    scoring_points = item.get("scoring_points") or ([explanation] if explanation else [])
    if not isinstance(scoring_points, list):
        scoring_points = [str(scoring_points)]
    question = Question(
        external_id=f"ai-plan-{plan.id}-{domain}-{index}",
        type="choice",
        difficulty=str(item.get("difficulty", "practical")),
        category=domain,
        stem=str(item.get("stem", "")),
        options=[str(o) for o in item.get("options", [])],
        correct_answer=str(item.get("correct_answer", "")).upper(),
        explanation=explanation,
        scoring_points=[str(p) for p in scoring_points],
        tags=[domain, "ai"],
        source_url=str(item.get("source_url", "")),
        verified_at=date.today(),
        is_core=True,
        enabled=True,
    )
    session.add(question)


def generate_for_plan(
    session: Session,
    plan: QuestionPlan,
    cfg: LlmConfig,
    timeout: float,
) -> dict[str, Any]:
    """Generate all domains of a confirmed plan. Returns
    {created, failed_domains} and updates the plan row."""
    domains: Sequence[dict[str, Any]] = plan.plan_json.get("domains", [])
    created = 0
    failed: list[str] = []
    for entry in domains:
        domain = str(entry.get("domain", ""))
        count = int(entry.get("count", 0))
        difficulty = entry.get("difficulty") or {}
        items: list[dict[str, Any]] = []
        last_error = ""
        for attempt in range(MAX_DOMAIN_RETRIES + 1):
            try:
                items = generate_domain_questions(domain, count, difficulty, cfg, timeout)
                break
            except Exception as exc:  # noqa: BLE001 - per-domain retry
                last_error = str(exc)
                if attempt >= MAX_DOMAIN_RETRIES:
                    failed.append(domain)
        for index, item in enumerate(items, 1):
            _persist_question(session, plan, domain, index, item)
            created += 1
        plan.generated_count = created
        plan.error = last_error if failed and domain in failed else plan.error
        session.commit()

    plan.status = "done" if not failed else "failed"
    if failed:
        plan.error = f"待补领域: {', '.join(failed)}"
    else:
        plan.error = None
        _disable_other_plans(session, plan)
    session.commit()
    return {"created": created, "failed_domains": failed}


def _disable_other_plans(session: Session, plan: QuestionPlan) -> None:
    """Replace the active bank: disable questions from older done plans so the
    newest confirmed plan is the only source of the formal exam."""
    other_ids = session.scalars(
        select(QuestionPlan.id).where(
            QuestionPlan.id != plan.id, QuestionPlan.status == "done"
        )
    )
    for other_id in other_ids:
        old = session.scalars(
            select(Question).where(Question.external_id.like(f"ai-plan-{other_id}-%"))
        )
        for question in old:
            question.enabled = False
