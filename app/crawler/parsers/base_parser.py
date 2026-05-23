from __future__ import annotations

import re
from abc import ABC, abstractmethod

from bs4.element import Tag

from ..models.post import Post
from ..utils.markdown_converter import html_node_to_markdown, make_image_only_markdown


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

    @staticmethod
    def render_content_markdown(
        content_node: Tag | None,
        *,
        base_url: str | None = None,
        image_fallback_limit: int = 10,
    ) -> str:
        """본문 컨테이너 Tag를 Markdown 문자열로 변환한다.

        - Markdown 변환 결과가 비어 있고 이미지만 있는 경우 ``![alt](src)`` fallback을 생성한다.
        - 둘 다 비면 빈 문자열을 반환한다.
        - 호출 측은 비어 있을 때 attachments/image-only sentinel 같은 후처리를 직접 결정한다.
        """
        if content_node is None:
            return ""

        markdown = html_node_to_markdown(content_node, base_url=base_url)
        if markdown:
            return markdown

        return make_image_only_markdown(
            content_node.select("img"),
            base_url=base_url,
            limit=image_fallback_limit,
        )
