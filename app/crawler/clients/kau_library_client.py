from __future__ import annotations

from urllib.parse import urlencode, urljoin

from ..clients.base_client import BaseClient
from ..config import (
    LIBRARY_BASE_URL,
    LIBRARY_NOTICE_LIST_URL,
    REQUEST_DELAY_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    USER_AGENT,
    VERIFY_SSL,
)


class KAULibraryClient(BaseClient):
    def __init__(self) -> None:
        super().__init__(
            base_url=LIBRARY_BASE_URL,
            user_agent=USER_AGENT,
            timeout=REQUEST_TIMEOUT_SECONDS,
            request_delay=REQUEST_DELAY_SECONDS,
            verify_ssl=VERIFY_SSL,
        )
        self.notice_list_url = LIBRARY_NOTICE_LIST_URL

    def build_notice_list_url(self, page: int = 1) -> str:
        if page <= 1:
            return self.notice_list_url
        return f"{self.notice_list_url}?{urlencode({'page_num': page})}"

    def fetch_notice_list(self, page: int = 1) -> str | None:
        return self.get(self.build_notice_list_url(page), referer=self.notice_list_url)

    def build_notice_detail_url(self, sb_no: str) -> str:
        params = {"sb_no": sb_no}
        return urljoin(self.base_url, f"/sb/default_notice_view.mir?{urlencode(params)}")

    def fetch_notice_detail(self, detail_url: str) -> str | None:
        return self.get(detail_url, referer=self.notice_list_url)
