from __future__ import annotations

from urllib.parse import urlencode

from ..clients.base_client import BaseClient
from ..config import REQUEST_DELAY_SECONDS, REQUEST_TIMEOUT_SECONDS, USER_AGENT, VERIFY_SSL


class KAUASBTClient(BaseClient):
    """
    첨단분야 부트캠프사업단(asbt.kau.ac.kr) 공지 클라이언트.
    """

    def __init__(self, *, base_url: str, notice_list_url: str, notice_code: str = "notice") -> None:
        super().__init__(
            base_url=base_url,
            user_agent=USER_AGENT,
            timeout=REQUEST_TIMEOUT_SECONDS,
            request_delay=REQUEST_DELAY_SECONDS,
            verify_ssl=VERIFY_SSL,
        )
        self.notice_list_url = notice_list_url
        self.notice_code = notice_code

    def build_notice_list_url(self, *, page: int = 1) -> str:
        params = {
            "ptype": "list",
            "code": self.notice_code,
        }
        if page > 1:
            params["page"] = str(page)
        return f"{self.notice_list_url}?{urlencode(params)}"

    def fetch_notice_list(self, *, page: int = 1) -> str | None:
        page_url = self.build_notice_list_url(page=page)
        return self.get(page_url, referer=self.notice_list_url)

    def fetch_notice_detail(self, detail_url: str) -> str | None:
        return self.get(detail_url, referer=self.notice_list_url)
