from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from ..config import RESEARCH_SOURCE_NAME, RESEARCH_SOURCE_TYPE
from ..models.post import Post
from ..parsers.base_parser import BaseParser


class KAUResearchParser(BaseParser):
    """
    한국항공대학교 산학협력단(research.kau.ac.kr) 공지 파서.

    HTML 구조가 변경되면 이 파일 selector를 수정한다.
    """

    def __init__(
        self,
        *,
        source_name: str = RESEARCH_SOURCE_NAME,
        source_type: str = RESEARCH_SOURCE_TYPE,
        category_fallback: str | None = None,
    ) -> None:
        self.source_name = source_name
        self.source_type = source_type
        self.category_fallback = category_fallback

    def parse_post_items(self, html: str, page_url: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")

        items: list[dict] = []

        # 목록은 table.table_01 > tr 단위다.
        for row in soup.select("table.table_01 tr"):
            link = row.select_one("td.tit > a[href]")
            if not link:
                continue

            href = (link.get("href") or "").strip()
            if not href:
                continue

            absolute_url = urljoin(page_url, href)
            if "mode=read" not in absolute_url or "seq=" not in absolute_url:
                continue

            first_cell = row.select_one("td")
            marker_text = self.normalize_whitespace(first_cell.get_text(" ", strip=True) if first_cell else "")
            is_permanent_notice = "공지" in marker_text or "notice" in marker_text.lower()

            items.append(
                {
                    "url": absolute_url,
                    "is_permanent_notice": is_permanent_notice,
                }
            )

        if not items:
            for link in soup.select("a[href*='mode=read'][href*='seq=']"):
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

        lines: list[str] = []

        for child in content_node.children:
            if isinstance(child, NavigableString):
                raw_text = self.normalize_whitespace(str(child))
                if raw_text:
                    lines.append(raw_text)
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

        # 이미지 본문 fallback
        image_titles: list[str] = []
        image_count = 0
        for img in content_node.select("img"):
            image_count += 1
            title = self.normalize_whitespace((img.get("title") or img.get("alt") or "").replace("\xa0", " "))
            if title:
                image_titles.append(title)

        if image_titles:
            deduped = list(dict.fromkeys(image_titles))
            lines = [f"[이미지] {title}" for title in deduped[:10]]
            if len(deduped) > 10:
                lines.append(f"... 외 {len(deduped) - 10}개")
            return "\n".join(lines)

        if image_count > 0:
            return f"[이미지 본문] 텍스트 본문 없음 (이미지 {image_count}개)"

        return ""

    def _extract_published_at(self, soup: BeautifulSoup) -> str | None:
        node = soup.select_one("div.view_header .view_info .date")
        if not node:
            return None

        date_text = node.get_text(" ", strip=True)
        match = re.search(r"(\d{4}[./-]\d{1,2}[./-]\d{1,2})", date_text)
        if not match:
            return None

        raw_date = match.group(1).replace(".", "-").replace("/", "-")
        year, month, day = raw_date.split("-")
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

    def _extract_category(self, soup: BeautifulSoup) -> str | None:
        node = soup.select_one("div.article_tit h3")
        if node:
            category = self.normalize_whitespace(node.get_text(" ", strip=True))
            if category:
                return category
        return self.category_fallback

    def _extract_attachments(self, soup: BeautifulSoup, detail_url: str) -> list[dict]:
        attachments: list[dict] = []

        # 첨부는 div.view_attatch > p > a[href] 구조이며 href는 ../upfile/... 상대경로다.
        for link in soup.select("div.view_attatch a[href]"):
            href = (link.get("href") or "").strip()
            if not href:
                continue

            absolute_url = urljoin(detail_url, href)
            name = self.normalize_whitespace(
                link.get_text(strip=True) or urlparse(absolute_url).path.split("/")[-1]
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
