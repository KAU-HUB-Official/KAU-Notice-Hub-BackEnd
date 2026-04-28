from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from ..clients.base_client import BaseClient
from ..config import REQUEST_DELAY_SECONDS, REQUEST_TIMEOUT_SECONDS, USER_AGENT, VERIFY_SSL


class KAULMSClient(BaseClient):
    """
    KAU LMS ubboard(view.php/article.php) 클라이언트.
    """

    def __init__(self, *, base_url: str, notice_list_url: str) -> None:
        super().__init__(
            base_url=base_url,
            user_agent=USER_AGENT,
            timeout=REQUEST_TIMEOUT_SECONDS,
            request_delay=REQUEST_DELAY_SECONDS,
            verify_ssl=VERIFY_SSL,
        )
        self.notice_list_url = notice_list_url

    def build_notice_list_url(self, *, page: int = 1) -> str:
        parsed = urlparse(self.notice_list_url)
        query = parse_qs(parsed.query, keep_blank_values=True)

        if page > 1:
            query["p"] = [str(page)]
        else:
            query.pop("p", None)

        flat_query: dict[str, str] = {
            key: values[-1]
            for key, values in query.items()
            if values
        }
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urlencode(flat_query), ""))

    def fetch_notice_list(self, *, page: int = 1) -> str | None:
        page_url = self.build_notice_list_url(page=page)
        return self.get(page_url, referer=self.notice_list_url)

    def fetch_notice_detail(self, detail_url: str) -> str | None:
        return self.get(detail_url, referer=self.notice_list_url)
