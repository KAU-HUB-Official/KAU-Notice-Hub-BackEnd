from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..models.post import Post
from ..parsers.base_parser import BaseParser


class KAUASBTParser(BaseParser):
    """
    첨단분야 부트캠프사업단(asbt.kau.ac.kr) 공지 파서.
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

        for row in soup.select("table tbody tr"):
            link = row.select_one("a[href*='ptype=view'][href*='idx=']")
            if not link:
                continue

            href = (link.get("href") or "").strip()
            if not href:
                continue

            absolute_url = urljoin(page_url, href)
            if "ptype=view" not in absolute_url or "idx=" not in absolute_url:
                continue

            row_classes = set(row.get("class") or [])
            first_cell = row.select_one("td")
            marker_text = self.normalize_whitespace(first_cell.get_text(" ", strip=True) if first_cell else "")
            is_permanent_notice = (
                "point" in row_classes
                or row.select_one(".notice, .m_notice") is not None
                or "공지" in marker_text
            )

            items.append(
                {
                    "url": absolute_url,
                    "is_permanent_notice": is_permanent_notice,
                }
            )

        if not items:
            for link in soup.select("a[href*='ptype=view'][href*='idx=']"):
                href = (link.get("href") or "").strip()
                if href:
                    items.append(
                        {
                            "url": urljoin(page_url, href),
                            "is_permanent_notice": False,
                        }
                    )

        deduped: list[dict] = []
        seen_urls: set[str] = set()
        for item in items:
            url = str(item.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            deduped.append(
                {
                    "url": url,
                    "is_permanent_notice": bool(item.get("is_permanent_notice")),
                }
            )

        return deduped

    def parse_post_urls(self, html: str, page_url: str) -> list[str]:
        return [str(item["url"]) for item in self.parse_post_items(html, page_url)]

    def parse_post(self, html: str, detail_url: str) -> Post:
        soup = BeautifulSoup(html, "html.parser")

        title = self._extract_title(soup)
        content = self._extract_content(soup, detail_url)
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
        node = soup.select_one("div.bbs_view h3.subject")
        if not node:
            return ""
        return self.normalize_whitespace(node.get_text(" ", strip=True))

    def _extract_content(self, soup: BeautifulSoup, detail_url: str) -> str:
        content_node = soup.select_one("div.bbs_view div.view_content")
        return self.render_content_markdown(content_node, base_url=detail_url)

    def _extract_published_at(self, soup: BeautifulSoup) -> str | None:
        for node in soup.select("div.bbs_view ul li"):
            text = node.get_text(" ", strip=True)
            if "작성일" not in text:
                continue

            match = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", text)
            if not match:
                continue
            year, month, day = match.groups()
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

        return None

    def _extract_category(self, soup: BeautifulSoup) -> str | None:
        node = soup.select_one("#subtitle h3")
        if node:
            category = self.normalize_whitespace(node.get_text(" ", strip=True))
            if category:
                return category
        return self.category_fallback

    def _extract_attachments(self, soup: BeautifulSoup, detail_url: str) -> list[dict]:
        attachments: list[dict] = []

        for link in soup.select("div.bbs_view div.view_file a[href]"):
            href = (link.get("href") or "").strip()
            if not href:
                continue

            absolute_url = urljoin(detail_url, href)
            name = self.normalize_whitespace(link.get_text(" ", strip=True))
            name = re.sub(r"^attach_file\s*", "", name, flags=re.IGNORECASE).strip()
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
