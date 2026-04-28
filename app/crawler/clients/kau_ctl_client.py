from __future__ import annotations

from urllib.parse import urlencode

from ..clients.base_client import BaseClient
from ..config import (
    CTL_BASE_URL,
    CTL_NOTICE_LIST_URL,
    REQUEST_DELAY_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    USER_AGENT,
    VERIFY_SSL,
)


class KAUCTLClient(BaseClient):
    def __init__(self) -> None:
        super().__init__(
            base_url=CTL_BASE_URL,
            user_agent=USER_AGENT,
            timeout=REQUEST_TIMEOUT_SECONDS,
            request_delay=REQUEST_DELAY_SECONDS,
            verify_ssl=VERIFY_SSL,
        )
        self.notice_list_url = CTL_NOTICE_LIST_URL

    def build_notice_list_url(self, *, code: str, page: int = 1) -> str:
        params = {
            "searchkey": "",
            "searchvalue": "",
            "code": code,
            "page": page,
        }
        return f"{self.notice_list_url}?{urlencode(params)}"

    def fetch_notice_list(self, *, code: str, page: int = 1) -> str | None:
        return self.get(self.build_notice_list_url(code=code, page=page), referer=self.notice_list_url)

    def fetch_notice_detail(self, detail_url: str) -> str | None:
        return self.get(detail_url, referer=self.notice_list_url)
