"""面试面试官 Agent：蓝图生成 / 逐轮应答 / 结构化报告。

- 蓝图：一次结构化调用产出 6-8 道题（开场 1 + 项目 2-3 + 技术 2 + 行为 1-2 + 收尾 1），
  行为题来自内置宝洁八大问模板 + 简历定制，不网搜。
- 逐轮应答：OpenAI chat.completions（stream=True，可选 query_bank 工具），正文末尾带
  `@@JSON@@` 元数据（action/score），由 runner 做流式裁剪与状态推进。
- 报告：面试结束一次结构化调用，从全量对话重建逐题上下文并打分。
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from .llm_provider import LlmConfig, build_openai_client

# 蓝图类型序列：开场 1 + 项目 2-3 + 技术 2 + 行为 1-2 + 收尾 1
BLUEPRINT_MIN = 6
BLUEPRINT_MAX = 8
METADATA_MARKER = "@@JSON@@"

# 报告元数据 schema（§8.5）
REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "overall_score": {"type": "number"},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "user_answer": {"type": "string"},
                    "score": {"type": "number"},
                    "max_score": {"type": "number"},
                    "corrections": {"type": "array", "items": {"type": "string"}},
                    "recommended_answer": {"type": "string"},
                    "principle": {"type": "string"},
                },
                "required": ["question", "user_answer", "score", "max_score"],
            },
        },
    },
    "required": ["summary", "overall_score", "questions"],
}


def _resume_summary(structured: dict[str, Any]) -> str:
    lines: list[str] = []
    skills = [s.get("name") for s in structured.get("skills", []) if isinstance(s, dict)]
    if skills:
        lines.append("技能：" + "、".join(str(s) for s in skills[:25]))
    for proj in structured.get("projects", [])[:6]:
        if isinstance(proj, dict):
            name = str(proj.get("name") or proj.get("title") or "")
            desc = str(proj.get("description") or proj.get("summary") or "").strip()
            if name:
                lines.append(f"- 项目「{name}」：{desc[:180]}")
    for exp in structured.get("experience", [])[:6]:
        if isinstance(exp, dict):
            role = str(exp.get("role") or exp.get("title") or "")
            company = str(exp.get("company") or "")
            if role:
                lines.append(f"- 经历：{role}@{company}".rstrip("@"))
    return "\n".join(lines) or "（简历信息较少）"


# ---- 蓝图生成 ----

BLUEPRINT_SYSTEM_PROMPT = (
    "你是资深技术面试官，正在为候选人设计一场 6-8 道题的模拟面试蓝图。\n"
    "题目结构固定为：开场 1 道 + 项目深挖 2-3 道 + 技术深度 2 道 + 行为面试 1-2 道 + 收尾 1 道。\n"
    "要求：\n"
    "1. 项目题基于简历里的真实项目追问细节（难点、取舍、量化结果）；\n"
    "2. 技术题优先覆盖简历技能与笔试弱项领域（weak_areas 里的领域重点考察），难度贴近真实面试；\n"
    "3. 行为题从提供的行为模板中选 1-2 个，结合简历经历定制，用 STAR 式问法；\n"
    "4. 语言中文；每道题一句话即可，作为面试官引导的提问核心。\n"
    "只输出一个 JSON 对象：\n"
    '{"questions": [{"type": "opening|project|tech|behavior|closing", "question": "题目文本", '
    '"focus": "考察点一句话", "category": "技术领域(tech 题可填)"}], "rationale": "简短设计说明"}'
)


def _validate_blueprint(data: Any) -> dict[str, Any]:
    questions = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(questions, list) or not questions:
        raise ValueError("蓝图缺少 questions")
    cleaned: list[dict[str, Any]] = []
    for item in questions:
        if not isinstance(item, dict):
            continue
        qtype = str(item.get("type", "")).strip()
        question = str(item.get("question", "")).strip()
        if qtype not in ("opening", "project", "tech", "behavior", "closing") or not question:
            continue
        cleaned.append(
            {
                "type": qtype,
                "question": question,
                "focus": str(item.get("focus") or ""),
                "category": str(item.get("category") or ""),
            }
        )
    if len(cleaned) < BLUEPRINT_MIN or len(cleaned) > BLUEPRINT_MAX:
        raise ValueError(f"蓝图题目数 {len(cleaned)} 不在 {BLUEPRINT_MIN}-{BLUEPRINT_MAX}")
    # 类型序列兜底重平衡：保证 opener/closer 在两端、project 2-3、tech 2、behavior 1-2
    types = [q["type"] for q in cleaned]
    if types[0] != "opening":
        cleaned.insert(
            0,
            {
                "type": "opening",
                "question": "请先简单介绍一下你自己。",
                "focus": "开场破冰",
            },
        )
    if types[-1] != "closing":
        cleaned.append(
            {"type": "closing", "question": "你有什么想问我的吗？", "focus": "收尾"}
        )
    if len(cleaned) > BLUEPRINT_MAX:
        cleaned = cleaned[: BLUEPRINT_MAX - 1] + [cleaned[-1]]
    return {"questions": cleaned, "rationale": str(data.get("rationale") or "")}


def generate_blueprint(
    structured: dict[str, Any],
    job_description: str,
    weak_areas: list[str],
    cfg: LlmConfig,
    timeout: float = 90.0,
) -> dict[str, Any]:
    """一次调用产出面试蓝图（6-8 题）。"""
    if not cfg.configured:
        raise ValueError("请先配置大模型")
    from .behavioral_templates import BEHAVIORAL_TEMPLATES

    user = json.dumps(
        {
            "resume_summary": _resume_summary(structured),
            "job_description": job_description,
            "weak_areas": weak_areas,
            "behavioral_templates": BEHAVIORAL_TEMPLATES,
        },
        ensure_ascii=False,
    )
    client = build_openai_client(cfg, timeout)
    last_error: Exception | None = None
    for _ in range(2):
        try:
            resp = client.chat.completions.create(
                model=cfg.model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": BLUEPRINT_SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
            )
            return _validate_blueprint(json.loads(resp.choices[0].message.content or "{}"))
        except (Exception, json.JSONDecodeError) as exc:  # noqa: BLE001
            last_error = exc
    raise ValueError(f"面试蓝图生成失败：{last_error}")


# ---- 逐轮应答 ----

INTERVIEWER_SYSTEM_PROMPT = (
    "你是严谨、专业又不失亲和的中文技术面试官，正在进行一场模拟面试。\n"
    "行为准则：\n"
    "1. 面试官驱动：你来提问、点评、追问；候选人答完一题，先简短点评（可给出 x/10 即时评分），"
    "再进入下一题或追问；\n"
    "2. 追问不超过 2 层，追问要深入、聚焦，不要漫无边际；\n"
    "3. 技术题可结合候选人的简历项目与笔试弱项领域提问；需要参考题库时调用 query_bank 工具"
    "（参数 category 填领域英文短名，如 mysql/redis），但不要直接念题干；\n"
    "4. 按面试蓝图推进题目，不要跳题或自行加题；收尾时给候选人提问机会，再总结结束；\n"
    "5. 回复用 Markdown，简洁有力，单条回复控制在 300 字以内。\n"
    "输出格式（严格遵守）：\n"
    "每条回复 = 正文（对候选人的点评/提问）+ 最后一行元数据：\n"
    f"以 {METADATA_MARKER} 开头，后跟一个 JSON 对象（不要有任何其它字符）：\n"
    '{"action": "followup" | "next" | "end", "score": {"score": 数字(0-10), "max_score": 10, '
    '"comment": "简短点评"} | null}\n'
    "- followup：就当前这道题继续追问；next：进入下一道题；end：结束面试（仅在蓝图最后一题、"
    "或候选人明确要求结束时使用）。\n"
    "- score 是对候选人刚才这次作答的即时评分，若本条不是评价作答（如开场白）则为 null。"
)

QUERY_BANK_TOOL = {
    "type": "function",
    "function": {
        "name": "query_bank",
        "description": "从本轮笔试题库中按领域查询题目（用于技术题出题参考）。",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "领域英文短名，如 mysql/redis/php"},
                "count": {"type": "integer", "description": "返回条数，默认 3"},
            },
            "required": ["category"],
        },
    },
}


def _strip_json_fence(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
    return content.strip()


def parse_turn_metadata(text: str) -> tuple[str, dict[str, Any] | None]:
    """Split a turn reply into (body, metadata). Body is the text before the
    @@JSON@@ marker; metadata is the parsed dict or None. Never raises."""
    if METADATA_MARKER in text:
        body, _, meta_raw = text.partition(METADATA_MARKER)
        body = body.rstrip()
        try:
            meta = json.loads(_strip_json_fence(meta_raw))
            if isinstance(meta, dict):
                return body, meta
        except json.JSONDecodeError:
            pass
    return text.strip(), None


def validate_metadata(meta: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a turn metadata dict to a safe {action, score}. Never raises."""
    if not isinstance(meta, dict):
        return {"action": "next", "score": None}
    action = meta.get("action")
    if action not in ("followup", "next", "end"):
        action = "next"
    score = meta.get("score")
    if isinstance(score, dict):
        raw_score = score.get("score")
        try:
            s = float(raw_score) if raw_score is not None else None
        except (TypeError, ValueError):
            s = None
        if s is not None:
            score = {
                "score": round(min(max(s, 0.0), 10.0), 1),
                "max_score": 10,
                "comment": str(score.get("comment") or ""),
            }
        else:
            score = None
    else:
        score = None
    return {"action": action, "score": score}


# ---- 报告生成 ----

REPORT_SYSTEM_PROMPT = (
    "你是技术面试官，根据完整面试记录生成一份结构化评估报告。\n"
    "要求：\n"
    "1. 从对话中提取每一道实质性题目（跳过开场寒暄与收尾寒暄），逐题给出：题目、候选人回答摘录、"
    "评分 score（满分 max_score=10）、改进建议 corrections（1-3 条）、推荐答案要点 "
    "recommended_answer、背后的考察原则 principle；\n"
    "2. 给出整体评分 overall_score（0-10）与书面总结 summary"
    "（优点、不足、针对性建议，200 字内）；\n"
    "3. 严格依据对话内容，不要臆造候选人没有说过的话。\n"
    "只输出符合给定 JSON schema 的对象。"
)


def generate_report(
    structured: dict[str, Any],
    job_description: str,
    transcript: list[dict[str, str]],
    blueprint: dict[str, Any],
    cfg: LlmConfig,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """面试结束的一次结构化调用，从全量对话生成报告。"""
    if not cfg.configured:
        raise ValueError("请先配置大模型")
    user = json.dumps(
        {
            "resume_summary": _resume_summary(structured),
            "job_description": job_description,
            "blueprint": blueprint,
            "transcript": transcript,
        },
        ensure_ascii=False,
    )
    client = build_openai_client(cfg, timeout)
    last_error: Exception | None = None
    for _ in range(2):
        try:
            resp = client.chat.completions.create(
                model=cfg.model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": REPORT_SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
            )
            data: dict[str, Any] = json.loads(
                resp.choices[0].message.content or "{}"
            )
            if not isinstance(data.get("questions"), list):
                raise ValueError("报告缺少 questions")
            return data
        except (Exception, json.JSONDecodeError) as exc:  # noqa: BLE001
            last_error = exc
    raise ValueError(f"面试报告生成失败：{last_error}")


# bank_tool 执行器（由 runner 注入）
BankFn = Callable[[str, int], list[dict[str, Any]]]
