from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    notice_json_path: Path = Path("./data/kau_official_posts.json")
    notice_db_path: Path = Path("./data/kau_notice_hub.db")
    # 연구 세션이 검수한 공지 적용 대상 라벨(JSONL). ingest 때마다 URL로 공지에 붙인다.
    # 파일이 없으면 라벨 없이 ingest하고, 목록의 target 필터는 모든 공지를 보여준다.
    notice_labels_path: Path = Path("./data/notice_labels.jsonl")
    # 연구 라벨이 없는 공지의 자동 라벨(게시판 규칙 + LLM). 크롤링 publish 뒤, ingest 전에 붙인다.
    # 켜져 있어도 OPENAI_API_KEY가 없으면 게시판 규칙 라벨만 붙인다.
    notice_auto_label_enabled: bool = False
    notice_auto_labels_path: Path = Path("./data/notice_labels_auto.jsonl")
    notice_auto_label_model: str = "gpt-6-luna"
    # 추론 모델의 reasoning.effort. 지정하면 temperature 대신 이 값을 보낸다. 추론 모델이 아닌
    # 모델(gpt-4.1-mini 등)로 바꾸면 빈 값으로 둔다. "none"이면 추론 토큰이 0이라 출력 비용이 거의 없다.
    notice_auto_label_reasoning_effort: str | None = "none"
    # 한 번 수집할 때 LLM에 보내는 공지 수 상한(비용 방어선). 남은 공지는 다음 수집 때 붙인다.
    notice_auto_label_max_llm_calls_per_run: int = 100
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
    # Per-IP 레이트리밋. api는 Caddy 뒤에 있고 Caddy가 X-Real-IP를 set 한다(app/rate_limit.py).
    # 값 형식은 slowapi/limits 표기("15/minute", "120/minute" 등). 테스트는 기본 비활성.
    rate_limit_enabled: bool = True
    rate_limit_chat: str = "15/minute"
    rate_limit_notices: str = "120/minute"
    # BFF(Next.js/Vercel) 프록시가 실제 브라우저 IP를 X-Client-IP로 전달할 때 쓰는
    # 공유 시크릿. 요청의 X-Internal-Token이 이 값과 일치할 때만 X-Client-IP를 신뢰한다.
    # 비어 있으면(기본) 전달 IP를 무시하고 Caddy가 set한 X-Real-IP(직접 peer)만 쓴다.
    internal_proxy_token: str | None = None
    rag_enabled: bool = False
    rag_max_references: int = 6
    rag_candidate_pool: int = 15
    rag_query_extraction_enabled: bool = True
    # 챗봇 Q/A 세션 로깅(평가셋·개선용). 켜져 있고 요청에 sessionId가 있을 때만
    # 별도 append 전용 SQLite 파일(chat_log_db_path)에 턴 단위로 저장한다.
    chat_logging_enabled: bool = False
    chat_log_db_path: Path = Path("./data/chat_sessions.db")
    # 카카오 로그인. REST API 키, 허용 redirect URI, JWT 서명 키(32자 이상) 중 하나라도
    # 없으면 POST /api/auth/kakao는 503을 반환하고 나머지 API는 그대로 동작한다.
    kakao_rest_api_key: str | None = None
    kakao_client_secret: str | None = None
    kakao_allowed_redirect_uris: str = ""
    # 앱 로그인(POST /api/auth/kakao/token)용 카카오 앱 ID. 앱이 보낸 토큰이 이 앱에서
    # 발급됐는지 확인한다. JWT 서명 키와 함께 없으면 앱 로그인만 503이다.
    kakao_app_id: str | None = None
    jwt_secret: str | None = None
    jwt_expire_seconds: int = 14 * 24 * 60 * 60
    # 사용자·북마크 DB. 공지 DB는 크롤링마다 통째로 교체되므로 별도 파일에 둔다.
    user_db_path: Path = Path("./data/users.db")
    # 사용자당 북마크 상한. GET /api/bookmarks/ids 응답 크기도 이 값으로 제한된다.
    bookmark_max_per_user: int = 500
    rate_limit_auth: str = "10/minute"
    rate_limit_bookmarks: str = "120/minute"

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

    @property
    def kakao_allowed_redirect_uri_list(self) -> list[str]:
        uris = [uri.strip() for uri in self.kakao_allowed_redirect_uris.split(",")]
        return [uri for uri in uris if uri]


@lru_cache
def get_settings() -> Settings:
    return Settings()
