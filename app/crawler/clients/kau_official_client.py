from __future__ import annotations

from urllib.parse import urlencode

from ..clients.base_client import BaseClient
from ..config import (
    BASE_URL,
    NOTICE_LIST_URL,
    REQUEST_DELAY_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    USER_AGENT,
    VERIFY_SSL,
)


class KAUOfficialClient(BaseClient):
    def __init__(self) -> None:
        super().__init__(
            base_url=BASE_URL,
            user_agent=USER_AGENT,
            timeout=REQUEST_TIMEOUT_SECONDS,
            request_delay=REQUEST_DELAY_SECONDS,
            verify_ssl=VERIFY_SSL,
        )
        self.notice_list_url = NOTICE_LIST_URL

    def build_board_list_url(self, *, list_url: str, code: str, page: int = 1) -> str:
        params = {
            "searchkey": "",
            "searchvalue": "",
            "code": code,
            "page": page,
        }
        return f"{list_url}?{urlencode(params)}"

    def build_notice_list_url(self, page: int = 1) -> str:
        return self.build_board_list_url(list_url=self.notice_list_url, code="s1101", page=page)

    def fetch_board_list(self, *, list_url: str, code: str, page: int = 1) -> str | None:
        page_url = self.build_board_list_url(list_url=list_url, code=code, page=page)
        return self.get(page_url, referer=list_url)

    def fetch_detail(self, detail_url: str, *, referer: str | None = None) -> str | None:
        return self.get(detail_url, referer=referer or self.notice_list_url)

    # Backward compatibility
    def fetch_notice_list(self, page: int = 1) -> str | None:
        return self.fetch_board_list(list_url=self.notice_list_url, code="s1101", page=page)

    def fetch_notice_detail(self, detail_url: str) -> str | None:
        return self.fetch_detail(detail_url, referer=self.notice_list_url)
