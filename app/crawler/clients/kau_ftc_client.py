from __future__ import annotations

from urllib.parse import urlencode

from ..clients.base_client import BaseClient
from ..config import (
    REQUEST_DELAY_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    USER_AGENT,
    VERIFY_SSL,
)


class KAUFTCClient(BaseClient):
    def __init__(self, *, base_url: str, notice_list_url: str) -> None:
        super().__init__(
            base_url=base_url,
            user_agent=USER_AGENT,
            timeout=REQUEST_TIMEOUT_SECONDS,
            request_delay=REQUEST_DELAY_SECONDS,
            verify_ssl=VERIFY_SSL,
        )
        self.notice_list_url = notice_list_url

    def build_notice_list_url(self, *, code: str, page: int = 1) -> str:
        params = {
            "searchkey": "",
            "searchvalue": "",
            "code": code,
            "page": page,
        }
        return f"{self.notice_list_url}?{urlencode(params)}"

    def fetch_notice_list(self, *, code: str, page: int = 1) -> str | None:
        page_url = self.build_notice_list_url(code=code, page=page)
        return self.get(page_url, referer=self.notice_list_url)

    def fetch_notice_detail(self, detail_url: str) -> str | None:
        return self.get(detail_url, referer=self.notice_list_url)
