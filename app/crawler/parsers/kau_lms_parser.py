from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..models.post import Post
from ..parsers.base_parser import BaseParser


class KAULMSParser(BaseParser):
    """
    KAU LMS ubboard 공지 파서.
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

        for row in soup.select("div.ubboard_list table.ubboard_table tbody tr"):
            link = row.select_one("a[href*='article.php'][href*='bwid=']")
            if not link:
                continue

            href = (link.get("href") or "").strip()
            if not href:
                continue

            absolute_url = urljoin(page_url, href)
            if "bwid=" not in absolute_url:
                continue

            first_cell = row.select_one("td")
            marker_text = self.normalize_whitespace(first_cell.get_text(" ", strip=True) if first_cell else "")
            is_permanent_notice = (
                row.select_one("img[alt*='공지'], img[src*='icon/notice']") is not None
                or marker_text == ""
                or marker_text == "-"
                or "공지" in marker_text
            )

            items.append(
                {
                    "url": absolute_url,
                    "is_permanent_notice": is_permanent_notice,
                }
            )

        if not items:
            for link in soup.select("a[href*='article.php'][href*='bwid=']"):
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
        node = soup.select_one("div.ubboard_view .subject")
        if not node:
            return ""
        return self.normalize_whitespace(node.get_text(" ", strip=True))

    def _extract_content(self, soup: BeautifulSoup, detail_url: str) -> str:
        content_node = soup.select_one("div.ubboard_view .content .text_to_html")
        if not content_node:
            content_node = soup.select_one("div.ubboard_view .content")
        return self.render_content_markdown(content_node, base_url=detail_url)

    def _extract_published_at(self, soup: BeautifulSoup) -> str | None:
        for node in soup.select("div.ubboard_view .date, div.ubboard_view .writer"):
            text = node.get_text(" ", strip=True)
            match = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", text)
            if not match:
                continue

            year, month, day = match.groups()
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

        view_node = soup.select_one("div.ubboard_view")
        if view_node:
            text = view_node.get_text(" ", strip=True)
            match = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", text)
            if match:
                year, month, day = match.groups()
                return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

        return None

    def _extract_category(self, soup: BeautifulSoup) -> str | None:
        breadcrumb_items = [
            self.normalize_whitespace(item.get_text(" ", strip=True))
            for item in soup.select("div.page-content-navigation ol.breadcrumb li")
            if self.normalize_whitespace(item.get_text(" ", strip=True))
        ]
        for item in reversed(breadcrumb_items):
            if item and item.upper() not in {"HOME"}:
                return item
        return self.category_fallback

    def _extract_attachments(self, soup: BeautifulSoup, detail_url: str) -> list[dict]:
        attachments: list[dict] = []

        for link in soup.select(
            "div.ubboard_view .attach a[href], "
            "div.ubboard_view .file a[href], "
            "div.ubboard_view a[href*='pluginfile.php'], "
            "div.ubboard_view a[href*='download.php']"
        ):
            href = (link.get("href") or "").strip()
            if not href:
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
