from __future__ import annotations

from urllib.parse import urlencode, urljoin

from ..clients.base_client import BaseClient
from ..config import (
    COLLEGE_BASE_URL,
    COLLEGE_NOTICE_LIST_URL,
    REQUEST_DELAY_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    USER_AGENT,
    VERIFY_SSL,
)


class KAUCollegeClient(BaseClient):
    def __init__(self) -> None:
        super().__init__(
            base_url=COLLEGE_BASE_URL,
            user_agent=USER_AGENT,
            timeout=REQUEST_TIMEOUT_SECONDS,
            request_delay=REQUEST_DELAY_SECONDS,
            verify_ssl=VERIFY_SSL,
        )
        self.notice_list_url = COLLEGE_NOTICE_LIST_URL
        self.list_api_url = urljoin(self.base_url, "/web/bbs/bbsListApi.gen")
        self.detail_api_url = urljoin(self.base_url, "/web/bbs/bbsViewApi.gen")

    def build_detail_url(
        self,
        *,
        site_flag: str,
        mnu_id: str,
        bbs_id: str,
        ntt_id: str,
    ) -> str:
        params = {
            "siteFlag": site_flag,
            "mnuId": mnu_id,
            "bbsId": bbs_id,
            "nttId": ntt_id,
            "bbsFlag": "View",
        }
        return f"{self.notice_list_url}?{urlencode(params)}"

    def fetch_notice_list(
        self,
        *,
        site_flag: str,
        bbs_id: str,
        bbs_auth: str,
        page_index: int,
        page_unit: int = 10,
    ) -> str | None:
        payload = {
            "siteFlag": site_flag,
            "bbsId": bbs_id,
            "pageIndex": page_index,
            "bbsAuth": bbs_auth,
            "pageUnit": page_unit,
        }
        # 해당 사이트 AJAX 호출은 이 헤더를 함께 전송한다.
        return self.post_json(
            self.list_api_url,
            payload,
            referer=self.notice_list_url,
            extra_headers={"AJAX": "true"},
        )

    def fetch_notice_detail(
        self,
        *,
        site_flag: str,
        bbs_id: str,
        ntt_id: str,
        mnu_id: str,
        bbs_auth: str,
    ) -> str | None:
        payload = {
            "siteFlag": site_flag,
            "bbsId": bbs_id,
            "nttId": ntt_id,
            "mnuId": mnu_id,
            "bbsAuth": bbs_auth,
        }
        return self.post_json(
            self.detail_api_url,
            payload,
            referer=self.notice_list_url,
            extra_headers={"AJAX": "true"},
        )

