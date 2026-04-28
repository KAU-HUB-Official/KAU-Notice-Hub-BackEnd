from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from ..config import CTL_SOURCE_NAME, CTL_SOURCE_TYPE
from ..models.post import Post
from ..parsers.base_parser import BaseParser


class KAUCTLParser(BaseParser):
    """
    한국항공대학교 교수학습센터(ctl.kau.ac.kr) 공지 파서.

    HTML 구조가 바뀌면 이 파일 selector를 수정한다.
    """

    def __init__(
        self,
        *,
        source_name: str = CTL_SOURCE_NAME,
        source_type: str = CTL_SOURCE_TYPE,
        category_fallback: str | None = None,
    ) -> None:
        self.source_name = source_name
        self.source_type = source_type
        self.category_fallback = category_fallback

    def parse_post_items(self, html: str, page_url: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")

        items: list[dict] = []

        # 목록 링크는 table.table_01 tr > td.tit > a[href] 구조를 사용한다.
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

        # 구조 변경 대비 fallback: mode=read + seq가 있는 링크를 직접 찾는다.
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
        # 상세 제목은 div.view_header > h4
        node = soup.select_one("div.view_header h4")
        if not node:
            return ""
        return self.normalize_whitespace(node.get_text(" ", strip=True))

    def _extract_content_text(self, soup: BeautifulSoup) -> str:
        # 본문은 div.view_conts 영역
        content_node = soup.select_one("div.view_conts")
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
        # 작성일은 div.view_header ul.info li 텍스트(예: 작성날짜 : 2025-07-22 10:12:50)
        for li in soup.select("div.view_header ul.info li"):
            text = li.get_text(" ", strip=True)
            if "작성날짜" not in text and "작성일" not in text:
                continue
            match = re.search(r"(\d{4}[./-]\d{1,2}[./-]\d{1,2})", text)
            if not match:
                continue
            raw = match.group(1).replace(".", "-").replace("/", "-")
            year, month, day = raw.split("-")
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

        return None

    def _extract_category(self, soup: BeautifulSoup) -> str | None:
        # breadcrumb 현재 위치(span.here)를 우선 사용하고, 없으면 fallback을 사용한다.
        node = soup.select_one("div.location span.here")
        if node:
            value = self.normalize_whitespace(node.get_text(" ", strip=True))
            if value:
                return value
        return self.category_fallback

    def _extract_attachments(self, soup: BeautifulSoup, detail_url: str) -> list[dict]:
        attachments: list[dict] = []

        # 첨부는 div.attach 또는 div.view_attatch 하위 a[href]에 노출된다.
        for link in soup.select("div.attach a[href], div.view_attatch a[href], li.attatch a[href]"):
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
