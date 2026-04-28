from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from ..models.post import Post
from ..parsers.base_parser import BaseParser


class KAUESLSCATParser(BaseParser):
    """
    eSLS CAT 공지 파서.

    목록은 javascript:goview(id) 패턴이며 상세는 notice_view.asp POST 응답 HTML이다.
    """

    def __init__(
        self,
        *,
        source_name: str,
        source_type: str,
        category_fallback: str | None = None,
    ) -> None:
        self.source_name = source_name
        self.source_type = source_type
        self.category_fallback = category_fallback

    def parse_post_items(self, html: str, page_url: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")

        items: list[dict] = []
        for link in soup.select("a[href*='javascript:goview(']"):
            href = (link.get("href") or "").strip()
            if not href:
                continue

            match = re.search(r"goview\((\d+)\)", href)
            if not match:
                continue
            notice_id = match.group(1)

            absolute_url = urljoin(page_url, f"notice_view.asp?id={notice_id}")
            items.append({"url": absolute_url, "is_permanent_notice": False})

        deduped: list[dict] = []
        seen_urls: set[str] = set()
        for item in items:
            url = str(item.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            deduped.append(item)
        return deduped

    def parse_post_urls(self, html: str, page_url: str) -> list[str]:
        return [str(item["url"]) for item in self.parse_post_items(html, page_url)]

    def parse_post(self, html: str, detail_url: str) -> Post:
        soup = BeautifulSoup(html, "html.parser")

        title = self._extract_title(soup)
        content = self._extract_content_text(soup)
        published_at = self._extract_published_at(soup)
        category_raw = self._extract_category(soup)
        attachments = self._extract_attachments(soup, detail_url)

        return Post(
            source_name=self.source_name,
            source_type=self.source_type,
            category_raw=category_raw,
            title=title,
            content=content,
            published_at=published_at,
            original_url=detail_url,
            attachments=attachments,
            crawled_at=datetime.now(timezone.utc).isoformat(),
        )

    def _extract_title(self, soup: BeautifulSoup) -> str:
        node = soup.select_one("table.tt_list thead th")
        if not node:
            return ""
        return self.normalize_whitespace(node.get_text(" ", strip=True))

    def _extract_content_text(self, soup: BeautifulSoup) -> str:
        content_node = soup.select_one("table.tt_list tbody tr:last-child td[colspan]")
        if not content_node:
            return ""

        lines: list[str] = []
        for child in content_node.children:
            if isinstance(child, NavigableString):
                text = self.normalize_whitespace(str(child))
                if text:
                    lines.append(text)
                continue

            if not isinstance(child, Tag):
                continue

            if child.name == "br":
                lines.append("")
                continue

            text = self.normalize_whitespace(child.get_text(" ", strip=True))
            if text:
                lines.append(text)

        if lines:
            return self.normalize_newlines("\n".join(lines))

        text = self.normalize_whitespace(content_node.get_text(" ", strip=True))
        if text:
            return self.normalize_newlines(text)

        image_count = len(content_node.select("img"))
        if image_count > 0:
            return f"[이미지 본문] 텍스트 본문 없음 (이미지 {image_count}개)"

        return ""

    def _extract_published_at(self, soup: BeautifulSoup) -> str | None:
        for row in soup.select("table.tt_list tbody tr"):
            label = self.normalize_whitespace(
                (row.select_one("td strong").get_text(" ", strip=True) if row.select_one("td strong") else "")
            )
            if "작성일" not in label:
                continue

            text = row.get_text(" ", strip=True)
            match = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", text)
            if not match:
                continue

            year, month, day = match.groups()
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

        return None

    def _extract_category(self, soup: BeautifulSoup) -> str | None:
        node = soup.select_one("li.sub_title")
        if node:
            category = self.normalize_whitespace(node.get_text(" ", strip=True))
            if category:
                return category
        return self.category_fallback

    def _extract_attachments(self, soup: BeautifulSoup, detail_url: str) -> list[dict]:
        attachments: list[dict] = []

        for row in soup.select("table.tt_list tbody tr"):
            label = self.normalize_whitespace(
                (row.select_one("td strong").get_text(" ", strip=True) if row.select_one("td strong") else "")
            )
            if "첨부파일" not in label:
                continue

            for link in row.select("a[href]"):
                href = (link.get("href") or "").strip()
                if not href:
                    continue
                if href.lower().startswith("javascript:"):
                    continue

                absolute_url = urljoin(detail_url, href)
                name = self.normalize_whitespace(link.get_text(" ", strip=True))
                if not name:
                    name = urlparse(absolute_url).path.split("/")[-1]
                attachments.append({"name": name, "url": absolute_url})

        deduped: list[dict] = []
        seen_urls: set[str] = set()
        for item in attachments:
            if item["url"] in seen_urls:
                continue
            seen_urls.add(item["url"])
            deduped.append(item)

        return deduped
