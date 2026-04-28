from __future__ import annotations

import re
from abc import ABC, abstractmethod

from ..models.post import Post


class BaseParser(ABC):
    @abstractmethod
    def parse_post_urls(self, html: str, page_url: str) -> list[str]:
        raise NotImplementedError

    def parse_post_items(self, html: str, page_url: str) -> list[dict]:
        """
        목록 항목 메타를 반환한다.
        기본 구현은 URL만 제공하며, 공지 유형(상시/일반)은 일반(False)으로 처리한다.
        """
        return [
            {"url": url, "is_permanent_notice": False}
            for url in self.parse_post_urls(html, page_url)
        ]

    @abstractmethod
    def parse_post(self, html: str, detail_url: str) -> Post:
        raise NotImplementedError

    @staticmethod
    def normalize_whitespace(text: str) -> str:
        return re.sub(r"[ \t]+", " ", text).strip()

    @staticmethod
    def normalize_newlines(text: str) -> str:
        text = text.replace("\r", "")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
