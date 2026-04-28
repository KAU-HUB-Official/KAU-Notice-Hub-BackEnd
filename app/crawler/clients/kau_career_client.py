from __future__ import annotations

from ..clients.base_client import BaseClient
from ..config import (
    CAREER_BASE_URL,
    CAREER_NOTICE_LIST_URL,
    REQUEST_DELAY_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    USER_AGENT,
    VERIFY_SSL,
)


class KAUCareerClient(BaseClient):
    def __init__(self) -> None:
        super().__init__(
            base_url=CAREER_BASE_URL,
            user_agent=USER_AGENT,
            timeout=REQUEST_TIMEOUT_SECONDS,
            request_delay=REQUEST_DELAY_SECONDS,
            # 사용자 요청으로 career 게시판은 robots 검사 예외 처리한다.
            respect_robots=False,
            verify_ssl=VERIFY_SSL,
        )
        self.notice_list_url = CAREER_NOTICE_LIST_URL

    def build_notice_list_url(self, page: int = 1) -> str:
        if page <= 1:
            return self.notice_list_url
        return f"{self.notice_list_url}/list/{page}"

    def fetch_notice_list(self, page: int = 1) -> str | None:
        return self.get(self.build_notice_list_url(page), referer=self.notice_list_url)

    def fetch_notice_detail(self, detail_url: str) -> str | None:
        return self.get(detail_url, referer=self.notice_list_url)
