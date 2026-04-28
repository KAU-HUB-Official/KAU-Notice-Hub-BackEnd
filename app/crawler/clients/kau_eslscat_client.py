from __future__ import annotations

from urllib.parse import urljoin

import requests

from ..clients.base_client import BaseClient
from ..config import REQUEST_DELAY_SECONDS, REQUEST_TIMEOUT_SECONDS, USER_AGENT, VERIFY_SSL


class KAUESLSCATClient(BaseClient):
    """
    eSLS CAT(토익 사이버 강좌) 공지 클라이언트.

    목록/상세가 EUC-KR 인코딩과 POST 폼 기반으로 동작한다.
    """

    def __init__(
        self,
        *,
        base_url: str,
        notice_list_url: str,
        respect_robots: bool = True,
    ) -> None:
        super().__init__(
            base_url=base_url,
            user_agent=USER_AGENT,
            timeout=REQUEST_TIMEOUT_SECONDS,
            request_delay=REQUEST_DELAY_SECONDS,
            verify_ssl=VERIFY_SSL,
            respect_robots=respect_robots,
        )
        self.notice_list_url = notice_list_url
        self.notice_view_url = urljoin(base_url, "/class/student/help/notice_view.asp")

    def build_notice_list_url(self, *, page: int = 1) -> str:
        if page <= 1:
            return self.notice_list_url
        return f"{self.notice_list_url}?page={page}"

    def fetch_notice_list(self, *, page: int = 1) -> str | None:
        if page <= 1:
            payload = self._request_get_bytes(self.notice_list_url, referer=self.notice_list_url)
        else:
            payload = self._request_post_bytes(
                self.notice_list_url,
                data={
                    "search_title1": "",
                    "search_title2": "",
                    "search_text": "",
                    "page": str(page),
                },
                referer=self.notice_list_url,
            )

        if payload is None:
            return None
        return self._decode_text(payload)

    def fetch_notice_detail(
        self,
        *,
        notice_id: str,
        page: str = "1",
        search_title1: str = "",
        search_title2: str = "",
        search_text: str = "",
    ) -> str | None:
        payload = self._request_post_bytes(
            self.notice_view_url,
            data={
                "id": notice_id,
                "page": page,
                "search_title1": search_title1,
                "search_title2": search_title2,
                "search_text": search_text,
            },
            referer=self.notice_list_url,
        )
        if payload is None:
            return None
        return self._decode_text(payload)

    def _request_get_bytes(self, url: str, *, referer: str | None = None) -> bytes | None:
        if not self.can_fetch(url):
            return None

        self._sleep_between_requests()
        headers: dict[str, str] = {}
        if referer:
            headers["Referer"] = referer

        try:
            response = self.session.get(
                url,
                headers=headers,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            self._request_count += 1
            response.raise_for_status()
            return response.content
        except requests.RequestException as exc:
            self.logger.error("요청 실패: %s (%s)", url, exc)
            return None

    def _request_post_bytes(
        self,
        url: str,
        *,
        data: dict[str, str],
        referer: str | None = None,
    ) -> bytes | None:
        if not self.can_fetch(url):
            return None

        self._sleep_between_requests()
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }
        if referer:
            headers["Referer"] = referer

        try:
            response = self.session.post(
                url,
                data=data,
                headers=headers,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            self._request_count += 1
            response.raise_for_status()
            return response.content
        except requests.RequestException as exc:
            self.logger.error("POST 요청 실패: %s (%s)", url, exc)
            return None

    @staticmethod
    def _decode_text(payload: bytes) -> str:
        for encoding in ("utf-8", "cp949", "euc-kr"):
            try:
                return payload.decode(encoding)
            except UnicodeDecodeError:
                continue

        # 일부 응답은 혼합 바이트가 포함되어 strict decode에 실패하므로
        # CP949/EUC-KR best-effort 디코딩으로 복구한다.
        for encoding in ("cp949", "euc-kr", "utf-8"):
            decoded = payload.decode(encoding, errors="replace")
            if decoded:
                return decoded

        return payload.decode("utf-8", errors="replace")
