"""LLM provider config: GUI-managed (app_settings) with .env fallback.

The app historically read three variables from .env (LLM_API_KEY /
LLM_BASE_URL / LLM_MODEL) through `Settings`. With the mock-interview
feature the user configures a provider in the settings page, persisted in
`app_settings["llm_provider"]`; the .env values stay as defaults so a bare
checkout still works.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from .config import Settings
from .models import AppSetting

PROVIDER_SETTING_KEY = "llm_provider"


@dataclass(frozen=True)
class LlmConfig:
    """Effective LLM connection config for one call."""

    api_key: str
    base_url: str = ""
    model: str = ""
    display_name: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model)


def read_provider(session: Any) -> dict[str, Any] | None:
    """Read the GUI-managed provider from app_settings, if any."""
    row = session.get(AppSetting, PROVIDER_SETTING_KEY)
    if row is None:
        return None
    value = row.value
    return value if isinstance(value, dict) and value.get("base_url") else None


def write_provider(session: Any, provider: dict[str, Any]) -> None:
    """Persist the GUI-managed provider."""
    row = session.get(AppSetting, PROVIDER_SETTING_KEY)
    if row:
        row.value = provider
    else:
        session.add(AppSetting(key=PROVIDER_SETTING_KEY, value=provider))
    session.commit()


def effective_llm_config(
    settings: Settings, provider: dict[str, Any] | None = None
) -> LlmConfig:
    """Merge the GUI provider over .env defaults."""
    p = provider or {}
    return LlmConfig(
        api_key=str(p.get("api_key") or settings.llm_api_key),
        base_url=str(p.get("base_url") or settings.llm_base_url),
        model=str(p.get("model") or settings.llm_model),
        display_name=str(p.get("display_name") or ""),
    )


def effective_llm_config_from_session(
    settings: Settings, session: Any
) -> LlmConfig:
    return effective_llm_config(settings, read_provider(session))


def build_openai_client(cfg: LlmConfig, timeout: float = 60.0) -> OpenAI:
    return OpenAI(
        api_key=cfg.api_key,
        base_url=cfg.base_url or None,
        timeout=timeout,
    )
