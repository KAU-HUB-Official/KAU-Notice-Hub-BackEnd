from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..models.post import Post
from ..parsers.base_parser import BaseParser


class KAUCardNoticeParser(BaseParser):
    """
    Parser for KAU card-style notice.php pages.
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

        for row in soup.select("ul.list_01 > li"):
            link = row.select_one("a[href*='mode=read'][href*='seq=']")
            if not link:
                continue

            href = (link.get("href") or "").strip()
            if not href:
                continue

            title = self.normalize_whitespace(link.get_text(" ", strip=True))
            row_classes = {str(cls).lower() for cls in (row.get("class") or [])}
            is_permanent_notice = (
                bool(row_classes & {"notice", "emp", "bo_notice"})
                or title.startswith("[공지]")
                or title.startswith("공지")
            )

            items.append(
                {
                    "url": urljoin(page_url, href),
                    "is_permanent_notice": is_permanent_notice,
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
        node = soup.select_one("div.view_header h4")
        if not node:
            return ""
        return self.normalize_whitespace(node.get_text(" ", strip=True))

    def _extract_content_text(self, soup: BeautifulSoup) -> str:
        content_node = soup.select_one("div.view_conts")
        if not content_node:
            return ""

        for tag in content_node(["script", "style"]):
            tag.decompose()

        for br in content_node.find_all("br"):
            br.replace_with("\n")

        raw_lines = [
            self.normalize_whitespace(line)
            for line in content_node.get_text("\n", strip=True).split("\n")
        ]
        lines = [line for line in raw_lines if line]
        if lines:
            return self.normalize_newlines("\n".join(lines))

        image_labels: list[str] = []
        image_count = 0
        for img in content_node.select("img"):
            image_count += 1
            label = self.normalize_whitespace(
                str(img.get("alt") or img.get("title") or "")
            )
            if label:
                image_labels.append(label)

        if image_labels:
            deduped = list(dict.fromkeys(image_labels))
            return "\n".join(f"[image] {label}" for label in deduped)

        if image_count > 0:
            return f"[image content] no text body (images: {image_count})"

        return ""

    def _extract_published_at(self, soup: BeautifulSoup) -> str | None:
        for node in soup.select("div.view_header ul.view_info li"):
            text = node.get_text(" ", strip=True)
            match = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", text)
            if not match:
                continue
            year, month, day = match.groups()
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        return None

    def _extract_category(self, soup: BeautifulSoup) -> str | None:
        location_items = [
            self.normalize_whitespace(item.get_text(" ", strip=True))
            for item in soup.select("ul.location li")
            if self.normalize_whitespace(item.get_text(" ", strip=True))
        ]
        if location_items:
            return location_items[-1]
        return self.category_fallback

    def _extract_attachments(self, soup: BeautifulSoup, detail_url: str) -> list[dict]:
        attachments: list[dict] = []

        for link in soup.select(
            "div.attach a[href], div.view_attatch a[href], div.view_file a[href]"
        ):
            href = (link.get("href") or "").strip()
            if not href:
                continue

            absolute_url = urljoin(detail_url, href)
            name = self.normalize_whitespace(
                (link.get("download") or "").strip()
                or link.get_text(" ", strip=True)
                or urlparse(absolute_url).path.split("/")[-1]
            )
            attachments.append({"name": name, "url": absolute_url})

        deduped: list[dict] = []
        seen_urls: set[str] = set()
        for item in attachments:
            if item["url"] in seen_urls:
                continue
            seen_urls.add(item["url"])
            deduped.append(item)

        return deduped
