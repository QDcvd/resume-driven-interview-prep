from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from ddgs import DDGS
from ddgs.exceptions import DDGSException
from openai import OpenAI

from .config import Settings
from .models import Question

VariantGenerator = Callable[[Question, int], list[dict[str, Any]]]

TRUSTED_DOMAINS = {
    "php.net",
    "www.php.net",
    "laravel.com",
    "vuejs.org",
    "developer.mozilla.org",
    "dev.mysql.com",
    "postgresql.org",
    "www.postgresql.org",
    "redis.io",
    "docs.docker.com",
    "git-scm.com",
    "fastapi.tiangolo.com",
    "docs.python.org",
    "github.com",
}


def _trusted(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in TRUSTED_DOMAINS or any(host.endswith(f".{domain}") for domain in TRUSTED_DOMAINS)


def search_evidence(question: Question, max_results: int) -> list[dict[str, str]]:
    query = f"{question.category} {question.stem} official documentation"
    try:
        raw_results = DDGS(timeout=12).text(
            query,
            region="wt-wt",
            safesearch="moderate",
            max_results=max_results * 3,
            backend="duckduckgo",
        )
    except DDGSException:
        return []
    evidence = []
    for item in raw_results:
        url = str(item.get("href", ""))
        body = str(item.get("body", "")).strip()
        if url and body and _trusted(url):
            evidence.append(
                {
                    "title": str(item.get("title", "Official documentation")),
                    "url": url,
                    "excerpt": body,
                }
            )
        if len(evidence) >= max_results:
            break
    return evidence


def build_variant_generator(settings: Settings) -> VariantGenerator:
    client = OpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url or None,
        timeout=settings.llm_timeout_seconds,
    )

    def generate(question: Question, count: int) -> list[dict[str, Any]]:
        evidence = search_evidence(question, settings.search_max_results)
        if not evidence:
            raise ValueError("DDG 未找到可信来源，已拒绝生成题目")
        prompt = {
            "original_question": question.stem,
            "category": question.category,
            "requested_count": count,
            "evidence": evidence,
            "requirements": (
                "只能根据 evidence 生成清晰的单选或多选题；每题必须引用一个 evidence URL，"
                "正确答案必须被对应 excerpt 直接支持，干扰项应可信但明确错误。"
            ),
        }
        completion = client.chat.completions.create(
            model=settings.llm_model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "返回 JSON 对象，唯一顶层字段 questions。每题字段为 stem,type,difficulty,"
                        "category,options,correct_answer,explanation,scoring_points,tags,source_url,"
                        "evidence_title,evidence_excerpt。不得使用证据之外的事实。"
                    ),
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
        )
        payload = json.loads(completion.choices[0].message.content or "{}")
        items = payload.get("questions", [])
        valid = []
        evidence_by_url = {item["url"]: item for item in evidence}
        for item in items[:count]:
            source_url = str(item.get("source_url", ""))
            source = evidence_by_url.get(source_url)
            if not source:
                continue
            item["evidence_title"] = source["title"]
            item["evidence_excerpt"] = source["excerpt"]
            valid.append(item)
        if not valid:
            raise ValueError("模型生成结果无法由检索来源核验，已拒绝保存")
        return valid

    return generate
