"""模拟面试会话编排：流式应答 + 状态机 + 滑动窗口/自动摘要。

每个 SSE 事件是一个 dict：{"type": "thinking|tool|token|status|done|error", ...}
- thinking: 开始
- tool:     面试官调用了 query_bank（可重复）
- token:    面试官回复的流式文本
- status:   进度提示（如“正在生成报告”）
- done:     本轮回合结束（含 action/score/message_id）
- error:    失败
"""
from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from .interview_agent import (
    INTERVIEWER_SYSTEM_PROMPT,
    METADATA_MARKER,
    QUERY_BANK_TOOL,
    generate_report,
    parse_turn_metadata,
    validate_metadata,
)
from .llm_provider import LlmConfig, build_openai_client
from .models import InterviewMessage, InterviewReport, InterviewSession

WINDOW_SIZE = 12          # 保留在 prompt 里的最近消息数
SUMMARY_REFRESH = 6       # 摘要刷新阈值：溢出增长到该值才重算
LOOKAHEAD = 400           # 元数据标记裁剪的流式前瞻长度
MAX_FOLLOW_UPS = 2

# 可注入 bank_tool 执行器签名
BankFn = Callable[[str, int], list[dict[str, Any]]]


def utcnow() -> datetime:
    return datetime.now(UTC)


def _resume_context(structured: dict[str, Any], job_description: str) -> str:
    lines: list[str] = []
    skills = [s.get("name") for s in structured.get("skills", []) if isinstance(s, dict)]
    if skills:
        lines.append("技能：" + "、".join(str(s) for s in skills[:25]))
    for proj in structured.get("projects", [])[:6]:
        if isinstance(proj, dict):
            name = str(proj.get("name") or proj.get("title") or "")
            desc = str(proj.get("description") or proj.get("summary") or "").strip()
            if name:
                lines.append(f"- 项目「{name}」：{desc[:200]}")
    for exp in structured.get("experience", [])[:6]:
        if isinstance(exp, dict):
            role = str(exp.get("role") or exp.get("title") or "")
            company = str(exp.get("company") or "")
            if role:
                lines.append(f"- 经历：{role}@{company}".rstrip("@"))
    if job_description:
        lines.append(f"目标岗位 JD：{job_description[:500]}")
    return "\n".join(lines) or "（简历信息较少）"


def build_system_prompt(
    session: InterviewSession,
    structured: dict[str, Any],
    job_description: str,
) -> str:
    blueprint = session.question_plan_json or {}
    questions = blueprint.get("questions") or []
    q_text: str = "\n".join(
        f"{i + 1}. [{q.get('type')}] {q.get('question')}"
        for i, q in enumerate(questions)
    )
    state = (
        f"当前阶段={session.stage}，蓝图题序号={session.current_index}/"
        f"{max(0, len(questions) - 1)}，本道题已追问 {session.follow_up_count} 层"
        f"（上限 {MAX_FOLLOW_UPS}）"
    )
    weak = "、".join(str(w) for w in (session.weak_areas or [])) or "（无）"
    return (
        INTERVIEWER_SYSTEM_PROMPT
        + "\n\n[面试背景]\n"
        + _resume_context(structured, job_description)
        + "\n[笔试弱项领域] " + weak
        + "\n[面试蓝图]（按序号推进）\n" + (q_text or "（无蓝图，自由提问）")
        + "\n[当前状态] " + state
    )


def build_conversation(
    session: InterviewSession,
    messages: list[InterviewMessage],
) -> str:
    parts: list[str] = []
    if session.context_summary:
        parts.append("[早期对话摘要]\n" + session.context_summary)
    window = messages[-WINDOW_SIZE:] if len(messages) > WINDOW_SIZE else messages
    for msg in window:
        who = "面试官" if msg.role == "interviewer" else "候选人"
        parts.append(f"{who}: {msg.content}")
    return "\n\n".join(parts) or "（对话尚未开始）"


def _summarize_history(text: str, cfg: LlmConfig, timeout: float = 60.0) -> str:
    client = build_openai_client(cfg, timeout)
    resp = client.chat.completions.create(
        model=cfg.model,
        messages=[
            {
                "role": "system",
                "content": "你是面试记录整理助手。把面试官与候选人的早期对话压缩成一段简洁的"
                "事实摘要（候选人身份、已讨论的题目与要点、候选人表现），供后续对话引用。"
                "只输出摘要文本，不要输出 JSON。",
            },
            {"role": "user", "content": text[:8000]},
        ],
        max_tokens=600,
    )
    return (resp.choices[0].message.content or "").strip()


def ensure_context_summary(
    db: Session,
    session: InterviewSession,
    messages: list[InterviewMessage],
    cfg: LlmConfig,
) -> None:
    """超出滑动窗口的早期消息做自动摘要，写入 session 并持久化。"""
    if len(messages) <= WINDOW_SIZE:
        return
    old_count = len(messages) - WINDOW_SIZE
    if session.context_summarized_upto >= old_count:
        return
    if (
        session.context_summarized_upto > 0
        and old_count - session.context_summarized_upto < SUMMARY_REFRESH
    ):
        return
    early = messages[:old_count]
    transcript = "\n".join(f"{m.role}: {m.content}" for m in early)
    try:
        summary = _summarize_history(transcript, cfg)
    except Exception:  # noqa: BLE001 - summary is best-effort
        summary = session.context_summary
    session.context_summary = summary
    session.context_summarized_upto = old_count
    db.add(session)
    db.commit()


def _tool_use_message(
    index: int, name: str, arguments: str, content: str = "", reasoning: str = ""
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "role": "assistant",
        "content": content or None,
        "tool_calls": [
            {
                "id": f"call_interview_{index}",
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        ],
    }
    if reasoning:
        msg["reasoning_content"] = reasoning
    return msg


def run_turn_events(
    db: Session,
    session: InterviewSession,
    structured: dict[str, Any],
    job_description: str,
    cfg: LlmConfig,
    bank_fn: BankFn | None,
) -> Iterator[dict[str, Any]]:
    """执行一轮面试对话，逐步 yield SSE 事件，并推进状态机。"""
    yield {"type": "thinking"}
    messages = list(session.messages)
    ensure_context_summary(db, session, messages, cfg)

    system = build_system_prompt(session, structured, job_description)
    convo = build_conversation(session, messages)
    chat_messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": convo},
    ]
    client = build_openai_client(cfg, timeout=120.0)

    body = ""
    meta: dict[str, Any] = {"action": "next", "score": None}
    tool_seq = 0
    try:
        while True:
            stream = client.chat.completions.create(
                model=cfg.model,
                messages=chat_messages,
                tools=[QUERY_BANK_TOOL],
                stream=True,
            )
            body_parts: list[str] = []
            lookahead = ""
            meta_raw: str | None = None
            tool_calls: dict[int, dict[str, str]] = {}
            saw_tool = False
            reasoning = ""
            pre_tool_text = ""
            for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                if choice is None:
                    continue
                delta = choice.delta
                if delta is None:
                    continue
                reasoning += getattr(delta, "reasoning_content", None) or ""
                if delta.tool_calls:
                    saw_tool = True
                    for tc in delta.tool_calls:
                        slot = tool_calls.setdefault(tc.index, {"name": "", "arguments": ""})
                        if tc.function and tc.function.name:
                            slot["name"] += tc.function.name
                        if tc.function and tc.function.arguments:
                            slot["arguments"] += tc.function.arguments
                content = delta.content or ""
                if saw_tool:
                    # 工具调用已出现：之后不再把文本当回复流给客户端，
                    # 收进 assistant content 供下一轮请求使用。
                    pre_tool_text += content
                    continue
                if meta_raw is not None:
                    meta_raw += content
                    continue
                lookahead += content
                idx = lookahead.find(METADATA_MARKER)
                if idx >= 0:
                    emit_part = lookahead[:idx]
                    if emit_part:
                        yield {"type": "token", "text": emit_part}
                        body_parts.append(emit_part)
                    meta_raw = lookahead[idx + len(METADATA_MARKER):]
                    lookahead = ""
                    continue
                if len(lookahead) > LOOKAHEAD:
                    safe = lookahead[:-LOOKAHEAD]
                    if safe:
                        yield {"type": "token", "text": safe}
                        body_parts.append(safe)
                    lookahead = lookahead[-LOOKAHEAD:]

            if tool_calls:
                for tc in tool_calls.values():
                    try:
                        args = json.loads(tc["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    yield {"type": "tool", "name": tc["name"], "args": args}
                    result: list[dict[str, Any]] = []
                    if tc["name"] == "query_bank" and bank_fn is not None:
                        try:
                            category = str(args.get("category") or "")
                            count = int(args.get("count") or 3)
                            result = bank_fn(category, count)
                        except Exception as exc:  # noqa: BLE001 - tool result is best-effort
                            yield {"type": "error", "message": f"题库查询失败：{exc}"}
                    chat_messages.append(
                        _tool_use_message(
                            tool_seq, tc["name"], tc["arguments"], pre_tool_text, reasoning
                        )
                    )
                    chat_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": f"call_interview_{tool_seq}",
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
                    tool_seq += 1
                continue

            # 最终文本
            if meta_raw is None:
                if lookahead:
                    yield {"type": "token", "text": lookahead}
                    body_parts.append(lookahead)
                body = "".join(body_parts).strip()
                meta = {"action": "next", "score": None}
            else:
                body = "".join(body_parts).strip()
                _, raw_meta = parse_turn_metadata(METADATA_MARKER + meta_raw)
                meta = validate_metadata(raw_meta)
            break
    except Exception as exc:  # noqa: BLE001 - surface as SSE error
        db.rollback()
        yield {"type": "error", "message": f"面试官回复失败：{exc}"}
        return

    # 持久化面试官消息
    if not body:
        body = "（本轮没有新内容）"
    interviewer_msg = InterviewMessage(
        session_id=session.id, role="interviewer", content=body
    )
    db.add(interviewer_msg)
    db.flush()

    # 即时评分：追加到当前蓝图题的 scores
    if meta.get("score") is not None:
        _append_score(session, meta["score"])

    # 状态机推进
    action = meta["action"]
    if action == "followup":
        session.follow_up_count = min(session.follow_up_count + 1, MAX_FOLLOW_UPS)
        session.stage = "followup"
    elif action == "next":
        session.current_index += 1
        session.follow_up_count = 0
        session.stage = "ask"
    elif action == "end":
        session.stage = "closing"
    db.commit()
    session.messages.append(interviewer_msg)

    yield {
        "type": "done",
        "message_id": interviewer_msg.id,
        "action": action,
        "score": meta.get("score"),
        "stage": session.stage,
        "current_index": session.current_index,
    }

    if action == "end":
        yield {"type": "status", "text": "面试已结束，正在生成评估报告…"}
        try:
            report = generate_report(
                structured,
                job_description,
                [{"role": m.role, "content": m.content} for m in session.messages],
                session.question_plan_json or {},
                cfg,
            )
            report_row = InterviewReport(
                session_id=session.id,
                summary_text=str(report.get("summary") or ""),
                score=float(report.get("overall_score") or 0),
                questions_json=report.get("questions") or [],
            )
            db.add(report_row)
            session.status = "ended"
            session.ended_at = utcnow()
            db.commit()
            yield {"type": "report", "id": report_row.id}
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            session.status = "ended"
            session.stage = "closing"
            session.ended_at = utcnow()
            db.commit()
            yield {"type": "error", "message": f"面试报告生成失败：{exc}"}


def _append_score(session: InterviewSession, score: dict[str, Any]) -> None:
    plan = session.question_plan_json or {}
    questions = plan.get("questions") or []
    idx = session.current_index
    if 0 <= idx < len(questions):
        entry = questions[idx]
        if isinstance(entry, dict):
            entry.setdefault("scores", []).append(score)
    session.question_plan_json = plan
