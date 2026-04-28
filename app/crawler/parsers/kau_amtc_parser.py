from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from ..models.post import Post
from ..parsers.base_parser import BaseParser


class KAUAMTCParser(BaseParser):
    """
    한국항공대학교 항공기술교육원(amtc.kau.ac.kr) 공지 파서.

    GNU board 기반 목록/상세 구조를 파싱한다.
    """

    def __init__(
        self,
        *,
        source_name: str,
        source_type: str,
        category_fallback: str | None = None,
        bo_table: str = "notice",
    ) -> None:
        self.source_name = source_name
        self.source_type = source_type
        self.category_fallback = category_fallback
        self.bo_table = bo_table

    def parse_post_items(self, html: str, page_url: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")

        items: list[dict] = []

        # 목록 본문은 li.board-list-body 단위이며 bo_notice 클래스가 상시 공지다.
        for row in soup.select("li.board-list-body"):
            link = row.select_one("a[href*='bo_table='][href*='wr_id=']")
            if not link:
                continue

            href = (link.get("href") or "").strip()
            if not href:
                continue

            absolute_url = urljoin(page_url, href)
            parsed = urlparse(absolute_url)
            query = parse_qs(parsed.query)
            if query.get("bo_table", [""])[-1] != self.bo_table:
                continue
            if not query.get("wr_id"):
                continue

            classes = set(row.get("class") or [])
            is_permanent_notice = "bo_notice" in classes or row.select_one(".notice_item") is not None

            items.append(
                {
                    "url": absolute_url,
                    "is_permanent_notice": is_permanent_notice,
                }
            )

        # fallback: 리스트 구조 변경 시 상세 링크를 직접 스캔한다.
        if not items:
            for link in soup.select("a[href*='bo_table='][href*='wr_id=']"):
                href = (link.get("href") or "").strip()
                if not href:
                    continue

                absolute_url = urljoin(page_url, href)
                parsed = urlparse(absolute_url)
                query = parse_qs(parsed.query)
                if query.get("bo_table", [""])[-1] != self.bo_table:
                    continue
                if not query.get("wr_id"):
                    continue

                items.append(
                    {
                        "url": absolute_url,
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
        for selector in ["#bo_v_title", ".bo_v_tit", "article#bo_v h1"]:
            node = soup.select_one(selector)
            if node:
                text = self.normalize_whitespace(node.get_text(" ", strip=True))
                if text:
                    return text
        return ""

    def _extract_content_text(self, soup: BeautifulSoup) -> str:
        content_node = soup.select_one("#bo_v_con")
        if not content_node:
            content_node = soup.select_one("#bo_v_atc")
        if not content_node:
            content_node = soup.select_one("article#bo_v")
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
        # 상세 상단 작성일(예: 작성일 26-04-16 13:12)을 YYYY-MM-DD로 정규화한다.
        for node in soup.select("strong.if_date, span.if_date, .if_date"):
            text = node.get_text(" ", strip=True)
            match = re.search(r"(\d{2,4})[./-](\d{1,2})[./-](\d{1,2})", text)
            if not match:
                continue

            year_raw, month, day = match.groups()
            if len(year_raw) == 2:
                year = 2000 + int(year_raw)
            else:
                year = int(year_raw)
            return f"{year:04d}-{int(month):02d}-{int(day):02d}"

        return None

    def _extract_category(self, soup: BeautifulSoup) -> str | None:
        # 페이지 title의 앞부분(예: 일반/학사공지)을 카테고리로 우선 사용한다.
        if soup.title:
            title_text = self.normalize_whitespace(soup.title.get_text(" ", strip=True))
            if title_text:
                category = title_text.split("|", 1)[0].strip()
                category = re.sub(r"\s+\d+\s*페이지$", "", category).strip()
                if category:
                    return category
        return self.category_fallback

    def _extract_attachments(self, soup: BeautifulSoup, detail_url: str) -> list[dict]:
        attachments: list[dict] = []

        # 첨부는 #bo_v_file a[href] 또는 download.php 링크로 제공된다.
        for link in soup.select("#bo_v_file a[href], a[href*='download.php']"):
            href = (link.get("href") or "").strip()
            if not href:
                continue

            absolute_url = urljoin(detail_url, href)
            name = self.normalize_whitespace(link.get_text(" ", strip=True))
            name = re.sub(r"\s+\([^\)]*\)$", "", name).strip()
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
