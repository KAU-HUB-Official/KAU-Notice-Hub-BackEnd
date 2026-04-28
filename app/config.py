from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    notice_json_path: Path = Path("./data/kau_official_posts.json")
    backend_cors_origins: str = "http://localhost:3000"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    log_level: str = "INFO"
    crawler_scheduler_enabled: bool = False
    crawler_interval_seconds: int = 3 * 60 * 60
    crawler_run_on_startup: bool = True
    crawler_max_pages: int = 0
    crawler_min_records: int = 1
    crawler_min_retain_ratio: float = 0.5
    crawler_lock_path: Path | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origins(self) -> list[str]:
        origins = [origin.strip() for origin in self.backend_cors_origins.split(",")]
        return [origin for origin in origins if origin]


@lru_cache
def get_settings() -> Settings:
    return Settings()
