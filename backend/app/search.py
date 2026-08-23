"""Web search: DeepSeek native server-side `web_search` tool, ddgs fallback.

The LLM provider's Anthropic-compatible endpoint (`{base}/anthropic/v1/messages`)
supports the `web_search_20250305` server tool: DeepSeek runs the search on its
own servers and returns structured `web_search_result` items. No MCP server, no
scraping, no separate process. Each result carries title + url; snippets are
encrypted server-side so `excerpt` is empty (the research/question pipeline
verifies `source_url` against these urls, which is all it needs). Falls back to
ddgs when the native call fails or the provider isn't configured.
"""
from __future__ import annotations

import logging

import httpx

from .llm_provider import LlmConfig

log = logging.getLogger(__name__)

ANTHROPIC_VERSION = "2023-06-01"
NATIVE_SEARCH_TIMEOUT = 60.0


def web_search(
    query: str,
    max_results: int = 6,
    cfg: LlmConfig | None = None,
) -> list[dict[str, str]]:
    """Search the web, returning [{title, url, excerpt}]. Never raises."""
    if cfg is not None and cfg.configured:
        items = _search_native(query, max_results, cfg)
        if items:
            return items
    return _search_via_ddgs(query, max_results)


def anthropic_messages_url(cfg: LlmConfig) -> str:
    """The Anthropic-compatible /messages endpoint for a provider."""
    base = (cfg.base_url or "").strip().rstrip("/")
    return f"{base}/anthropic/v1/messages"


def _search_native(
    query: str, max_results: int, cfg: LlmConfig
) -> list[dict[str, str]]:
    try:
        payload = {
            "model": cfg.model,
            "max_tokens": 4096,
            "messages": [
                {"role": "user", "content": f"Perform a web search for the query: {query}"}
            ],
            "tools": [
                {"type": "web_search_20250305", "name": "web_search", "max_uses": 1}
            ],
        }
        response = httpx.post(
            anthropic_messages_url(cfg),
            json=payload,
            headers={
                "x-api-key": cfg.api_key,
                "content-type": "application/json",
                "anthropic-version": ANTHROPIC_VERSION,
            },
            timeout=NATIVE_SEARCH_TIMEOUT,
        )
        response.raise_for_status()
        blocks = response.json().get("content", [])
    except Exception as exc:  # noqa: BLE001 - any native failure degrades to ddgs
        log.warning("DeepSeek native search failed (%s), falling back to ddgs", exc)
        return []

    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for block in blocks:
        if block.get("type") != "web_search_tool_result":
            continue
        for result in block.get("content", []) or []:
            if not isinstance(result, dict):
                continue
            url = str(result.get("url", "")).strip()
            if not url or url in seen:
                continue
            seen.add(url)
            items.append(
                {
                    "title": str(result.get("title", "")).strip(),
                    "url": url,
                    "excerpt": "",
                }
            )
            if len(items) >= max_results:
                return items
    return items


def _search_via_ddgs(query: str, max_results: int) -> list[dict[str, str]]:
    try:
        from ddgs import DDGS
    except ImportError:
        return []

    try:
        raw = DDGS(timeout=12).text(
            query,
            region="wt-wt",
            safesearch="moderate",
            max_results=max_results * 3,
            backend="duckduckgo",
        )
    except Exception:  # noqa: BLE001 - degrade on any search failure
        return []

    items: list[dict[str, str]] = []
    for item in raw or []:
        url = str(item.get("href", ""))
        body = str(item.get("body", "")).strip()
        if url and body:
            items.append(
                {
                    "title": str(item.get("title", "")),
                    "url": url,
                    "excerpt": body,
                }
            )
        if len(items) >= max_results:
            break
    return items
