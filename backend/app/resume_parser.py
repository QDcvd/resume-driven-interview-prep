"""Resume parsing pipeline.

Two local paths feed one LLM structure extraction:

1. Text-layer PDFs go through MarkItDown (pdfminer-based) straight to Markdown.
2. Scanned PDFs (no usable text layer) are rendered to page images with
   pymupdf and read through the configured OpenAI-compatible vision model.

Everything runs locally except the optional vision call, which uses the same
LLM the rest of the app already depends on. No external document service.
"""
from __future__ import annotations

import base64
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .llm_provider import LlmConfig, build_openai_client

# Below this many non-whitespace characters the text layer is treated as
# missing (scanned document) and the vision path takes over.
MIN_TEXT_CHARS = 40

# Injectable parser signature: (file_path, job_description, cfg, timeout)
# -> (markdown, structured, source). Mirrors the grade/variant provider DI.
ResumeParser = Callable[[Path, str, "LlmConfig", float], tuple[str, dict[str, Any], str]]


def _markdown_via_markitdown(file_path: Path) -> str:
    from markitdown import MarkItDown

    converter = MarkItDown()
    result = converter.convert(str(file_path))
    return result.text_content or ""


def _render_pages(file_path: Path, max_pages: int = 6) -> list[bytes]:
    import pymupdf

    doc = pymupdf.open(str(file_path))
    page_count = min(doc.page_count, max_pages)
    images: list[bytes] = []
    for index in range(page_count):
        page = doc[index]
        pix = page.get_pixmap(dpi=150)
        images.append(pix.tobytes("png"))
    doc.close()
    return images


def _markdown_via_vision(file_path: Path, cfg: LlmConfig, timeout: float) -> str:
    """Read a scanned PDF through the configured vision-capable LLM."""
    if not cfg.configured:
        raise ValueError("扫描版简历需要视觉模型：请先在设置中配置大模型")
    images = _render_pages(file_path)
    client = build_openai_client(cfg, timeout)
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "这是一份扫描版简历的页面图片。请逐页完整转录为 Markdown："
                "保留章节标题、项目符号、日期、技术名词；不要概括，不要遗漏。"
                "只输出转录文本。"
            ),
        }
    ]
    for image in images:
        encoded = base64.b64encode(image).decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{encoded}"},
            }
        )
    completion = client.chat.completions.create(
        model=cfg.model,
        temperature=0,
        messages=[{"role": "user", "content": content}],
    )
    return completion.choices[0].message.content or ""


def parse_pdf_to_markdown(
    file_path: Path, cfg: LlmConfig, timeout: float = 60.0
) -> tuple[str, str]:
    """Convert a PDF to Markdown. Returns (markdown, source).

    source is one of "markitdown" | "ocr". Raises ValueError on unreadable
    documents.
    """
    text = _markdown_via_markitdown(file_path)
    if len("".join(text.split())) >= MIN_TEXT_CHARS:
        return text, "markitdown"
    # Too little text -> scanned pages. Fall back to vision OCR.
    return _markdown_via_vision(file_path, cfg, timeout), "ocr"


STRUCTURE_SYSTEM_PROMPT = (
    "你是严谨的简历解析器。根据简历 Markdown 文本与目标岗位描述，提取结构化 JSON。"
    "字段必须包含 basic, skills, projects, experience, education, summary。"
    "skills 每项含 name/level/keywords；projects 每项含 name/role/tech_stack/"
    "description/highlights；experience 每项含 company/role/duration/responsibilities；"
    "education 每项含 school/degree/major/period；summary 为 3-5 句总结。"
    "缺失的信息填空字符串或空数组，不要编造。"
)


def extract_structured_resume(
    markdown: str, job_description: str, cfg: LlmConfig, timeout: float = 60.0
) -> dict[str, Any]:
    """Extract structured resume fields from parsed Markdown via the LLM."""
    if not cfg.configured:
        raise ValueError("请先配置大模型")
    client = build_openai_client(cfg, timeout)
    payload = {
        "resume_markdown": markdown,
        "job_description": job_description,
    }
    completion = client.chat.completions.create(
        model=cfg.model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": STRUCTURE_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    )
    content = completion.choices[0].message.content or "{}"
    data: dict[str, Any] = json.loads(content)
    # Ensure the required top-level keys always exist.
    data.setdefault("basic", {})
    data.setdefault("skills", [])
    data.setdefault("projects", [])
    data.setdefault("experience", [])
    data.setdefault("education", [])
    data.setdefault("summary", "")
    return data


def parse_resume(
    file_path: Path, job_description: str, cfg: LlmConfig, timeout: float = 60.0
) -> tuple[str, dict[str, Any], str]:
    """Full pipeline: PDF -> Markdown -> structured JSON. Returns
    (markdown, structured, source)."""
    markdown, source = parse_pdf_to_markdown(file_path, cfg, timeout)
    if not "".join(markdown.split()):
        raise ValueError("无法从简历中提取任何文本")
    structured = extract_structured_resume(markdown, job_description, cfg, timeout)
    return markdown, structured, source
