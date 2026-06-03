from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    notice_json_path: Path = Path("./data/kau_official_posts.json")
    notice_db_path: Path = Path("./data/kau_notice_hub.db")
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
    # 빈 값이면 도메인 화이트리스트를 끄고 공개 IP로 해석되는 모든 호스트를 허용한다.
    # 공지 본문에는 외부 호스트 이미지가 섞여 들어오므로 기본은 개방으로 둔다.
    # localhost·사설/비공개 IP·non-http(s) 스킴 차단(SSRF 방어)은 그대로 유지된다.
    # 다시 특정 도메인으로 제한하려면 콤마로 구분한 도메인 목록을 지정한다.
    content_enrichment_allowed_domains: str = ""
    crawler_scheduler_enabled: bool = False
    crawler_interval_seconds: int = 3 * 60 * 60
    crawler_run_on_startup: bool = True
    crawler_max_pages: int = 0
    crawler_min_records: int = 1
    crawler_min_retain_ratio: float = 0.5
    crawler_lock_path: Path | None = None
    rag_enabled: bool = False
    rag_max_references: int = 6
    rag_candidate_pool: int = 15
    rag_query_extraction_enabled: bool = True

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
