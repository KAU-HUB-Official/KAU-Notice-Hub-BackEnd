from __future__ import annotations

from urllib.parse import urlencode, urljoin

from ..clients.base_client import BaseClient
from ..config import (
    ADMISSION_BASE_URL,
    ADMISSION_NOTICE_LIST_URL,
    REQUEST_DELAY_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    USER_AGENT,
    VERIFY_SSL,
)


class KAUAdmissionClient(BaseClient):
    def __init__(self) -> None:
        super().__init__(
            base_url=ADMISSION_BASE_URL,
            user_agent=USER_AGENT,
            timeout=REQUEST_TIMEOUT_SECONDS,
            request_delay=REQUEST_DELAY_SECONDS,
            verify_ssl=VERIFY_SSL,
        )
        self.notice_list_url = ADMISSION_NOTICE_LIST_URL

    def build_notice_list_url(
        self,
        *,
        list_url: str,
        board_id: str,
        site_type: str,
        page: int = 1,
    ) -> str:
        params = {
            "p_board_id": board_id,
            "p_site_type": site_type,
            "s_board_category": "",
            "s_admission_type": "",
            "s_search_type": "",
            "s_search_text": "",
            "page": page,
        }
        return f"{list_url}?{urlencode(params)}"

    def fetch_notice_list(
        self,
        *,
        list_url: str,
        board_id: str,
        site_type: str,
        page: int = 1,
    ) -> str | None:
        page_url = self.build_notice_list_url(
            list_url=list_url,
            board_id=board_id,
            site_type=site_type,
            page=page,
        )
        return self.get(page_url, referer=list_url)

    def build_detail_url(
        self,
        *,
        list_url: str,
        board_id: str,
        board_idx: str,
        page: int = 1,
    ) -> str:
        detail_base = urljoin(list_url, "noticeView.asp")
        params = {
            "p_board_id": board_id,
            "p_board_idx": board_idx,
            "page": page,
        }
        return f"{detail_base}?{urlencode(params)}"

    def fetch_notice_detail(self, detail_url: str, *, referer: str | None = None) -> str | None:
        return self.get(detail_url, referer=referer or self.notice_list_url)
