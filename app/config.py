from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    notice_json_path: Path = Path("./data/kau_official_posts.json")
    backend_cors_origins: str = "http://localhost:3000"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    log_level: str = "INFO"
    content_enrichment_enabled: bool = False
    content_enrichment_provider: str = "openai"
    content_enrichment_model: str = "gpt-4.1-mini"
    content_enrichment_fallback_model: str = "gpt-5.5"
    content_enrichment_image_detail: str = "high"
    content_enrichment_min_text_length: int = 30
    content_enrichment_max_assets_per_notice: int = 3
    content_enrichment_max_file_bytes: int = 10 * 1024 * 1024
    content_enrichment_max_calls_per_run: int = 50
    content_enrichment_allowed_domains: str = (
        "kau.ac.kr,career.kau.ac.kr,college.kau.ac.kr,research.kau.ac.kr,"
        "ibhak.kau.ac.kr,ctl.kau.ac.kr,lib.kau.ac.kr,ftc.kau.ac.kr,"
        "amtc.kau.ac.kr,fsc.kau.ac.kr,grad.kau.ac.kr,gradbus.kau.ac.kr,"
        "aisw.kau.ac.kr,lms.kau.ac.kr,asbt.kau.ac.kr"
    )
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

    @property
    def content_enrichment_allowed_domain_list(self) -> list[str]:
        domains = [
            domain.strip().lower()
            for domain in self.content_enrichment_allowed_domains.split(",")
        ]
        return [domain for domain in domains if domain]


@lru_cache
def get_settings() -> Settings:
    return Settings()
