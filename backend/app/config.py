from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "基于简历的面试考试系统"
    database_url: str = "sqlite:///data/interview_exam.db"
    exam_duration_minutes: int = 150
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_max_concurrency: int = 2
    llm_timeout_seconds: float = 60.0
    llm_max_batch_size: int = 30
    interview_date: date = date(2026, 8, 11)
    search_max_results: int = 8

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def ensure_sqlite_directory(self) -> None:
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            path = Path(self.database_url.removeprefix(prefix))
            if path.parent != Path("."):
                path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
