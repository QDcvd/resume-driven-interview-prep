"""Research agent: resume + JD -> 50-question plan via DeepSeek native search.

A single Anthropic-compatible Messages call. DeepSeek runs its native
`web_search_20250305` server tool (up to `max_uses` searches) inside that one
call and the model writes the plan JSON in its final text block. No MCP server,
no separate search roundtrips, no agent framework.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import httpx

from .llm_provider import LlmConfig
from .search import ANTHROPIC_VERSION, anthropic_messages_url

PLAN_TOTAL = 50
MAX_NATIVE_SEARCHES = 8

# Injectable research signature: (structured, job_description, cfg, timeout)
# -> validated plan dict.
ResearchFn = Callable[[dict[str, Any], str, "LlmConfig", float], dict[str, Any]]

RESEARCH_SYSTEM_PROMPT = (
    "你是资深技术面试出题官。根据候选人的简历和目标岗位工作描述(JD)，先用 web_search "
    "工具搜索真实的技术面试题与岗位要求（可多次搜索不同技术栈），然后产出一份"
    "【50 道客观选择题】的题目规划表。\n"
    "规划表是 JSON 对象，字段：\n"
    '- "domains": 数组，每项为 {"domain": 技术领域名(英文短名, 如 mysql/redis/php), '
    '"count": 该领域题量, "difficulty": {"basic": n, "practical": n, "deep": n}}\n'
    '- "rationale": 字符串，调研依据摘要（说明为什么这些领域、这些题量）\n'
    '- "total": 50\n'
    "要求：\n"
    "1. 领域来自 JD 的技术栈要求与简历中的技能/项目，通常 6-10 个领域；\n"
    "2. 所有领域 count 之和必须恰好等于 50；每个领域的 difficulty 三级之和等于该域 count；\n"
    "3. 难度以 practical 为主，deep 少量；\n"
    "4. 领域名用英文小写短名，稳定且能用于分类。\n"
    "搜索完成后，只输出这个 JSON 对象，不要输出其他任何内容。"
)


def _strip_json_fence(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
    return content.strip()


def _validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    domains = plan.get("domains")
    if not isinstance(domains, list) or len(domains) < 3:
        raise ValueError("规划表缺少有效的 domains")
    total = 0
    cleaned: list[dict[str, Any]] = []
    for item in domains:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain", "")).strip().lower()
        try:
            count = int(item.get("count", 0))
        except (TypeError, ValueError):
            count = 0
        if not domain or count <= 0:
            continue
        difficulty = item.get("difficulty") or {}
        basic = int(difficulty.get("basic", 0) or 0)
        practical = int(difficulty.get("practical", 0) or 0)
        deep = int(difficulty.get("deep", 0) or 0)
        if basic + practical + deep != count:
            gap = count - (basic + practical + deep)
            if gap > 0:
                practical += gap
            elif gap < 0:
                deep = max(0, deep + gap)
        total += count
        cleaned.append(
            {
                "domain": domain,
                "count": count,
                "difficulty": {"basic": basic, "practical": practical, "deep": deep},
            }
        )
    if not cleaned:
        raise ValueError("规划表没有有效的领域")
    if total != PLAN_TOTAL:
        raise ValueError(f"领域题量合计 {total}，应为 {PLAN_TOTAL}")
    plan["domains"] = cleaned
    plan["total"] = PLAN_TOTAL
    plan["rationale"] = str(plan.get("rationale") or "")
    return plan


def _parse_plan_from_text(text: str) -> dict[str, Any]:
    plan = json.loads(_strip_json_fence(text))
    return _validate_plan(plan)


def research_plan(
    structured: dict[str, Any],
    job_description: str,
    cfg: LlmConfig,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Run native research (server-side search + plan) and return a validated
    plan dict. Retries once when the plan text is missing or unparseable."""
    if not cfg.configured:
        raise ValueError("请先配置大模型")
    summary = {
        "skills": [s.get("name") for s in structured.get("skills", [])][:20],
        "projects": [p.get("name") for p in structured.get("projects", [])][:8],
        "experience": [e.get("role") for e in structured.get("experience", [])][:8],
    }
    user_content = json.dumps(
        {"resume_summary": summary, "job_description": job_description},
        ensure_ascii=False,
    )
    payload = {
        "model": cfg.model,
        "max_tokens": 4096,
        "system": RESEARCH_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_content}],
        "tools": [
            {"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_NATIVE_SEARCHES}
        ],
    }
    headers = {
        "x-api-key": cfg.api_key,
        "content-type": "application/json",
        "anthropic-version": ANTHROPIC_VERSION,
    }
    last_error: Exception | None = None
    for _ in range(2):
        try:
            response = httpx.post(
                anthropic_messages_url(cfg), json=payload, headers=headers, timeout=timeout
            )
            response.raise_for_status()
            blocks = response.json().get("content", [])
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            if not text.strip():
                raise ValueError("调研 Agent 未返回规划表内容")
            return _parse_plan_from_text(text)
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
    raise ValueError(f"调研 Agent 输出无法解析或校验失败：{last_error}")
