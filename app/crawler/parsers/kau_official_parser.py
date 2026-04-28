from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from ..config import SOURCE_NAME, SOURCE_TYPE
from ..models.post import Post
from ..parsers.base_parser import BaseParser


class KAUOfficialParser(BaseParser):
    """
    KAU 공식 홈페이지 공지 파서.

    HTML 구조가 변경되면 이 파일의 selector를 우선 수정하면 된다.
    """

    def __init__(
        self,
        *,
        source_name: str = SOURCE_NAME,
        source_type: str = SOURCE_TYPE,
    ) -> None:
        self.source_name = source_name
        self.source_type = source_type

    def parse_post_items(self, html: str, page_url: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")

        items: list[dict] = []

        # 목록 페이지는 table.table_board > tbody > tr 단위다.
        for row in soup.select("table.table_board tbody tr"):
            link = row.select_one("td.title a[href], td.tit a[href]")
            if not link:
                continue

            href = (link.get("href") or "").strip()
            if not href:
                continue

            absolute_url = urljoin(page_url, href)
            if "mode=read" not in absolute_url or "seq=" not in absolute_url:
                continue

            row_classes = set(row.get("class") or [])
            is_permanent_notice = (
                "emp" in row_classes
                or row.select_one("img.icon_notice, img[alt*='공지'], span.notice, .icon_notice") is not None
            )
            first_cell = row.select_one("td")
            marker_text = self.normalize_whitespace(first_cell.get_text(" ", strip=True) if first_cell else "")
            if not is_permanent_notice:
                is_permanent_notice = bool(
                    marker_text and (("공지" in marker_text) or (not marker_text.isdigit()))
                )

            items.append(
                {
                    "url": absolute_url,
                    "is_permanent_notice": is_permanent_notice,
                }
            )

        # 구조 변경 대비용 fallback selector.
        if not items:
            for link in soup.select("table.table_board tbody a[href*='mode=read'][href*='seq=']"):
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
        # 상세 제목은 div.view_header > h4 에 위치한다.
        title_node = soup.select_one("div.view_header h4")
        if not title_node:
            return ""
        return self.normalize_whitespace(title_node.get_text(" ", strip=True))

    def _extract_content_text(self, soup: BeautifulSoup) -> str:
        # 상세 본문은 div.view_conts 영역이다.
        content_node = soup.select_one("div.view_conts")
        if not content_node:
            return ""

        lines: list[str] = []

        # span 단위로 잘게 분할된 HTML이 많아, 직계 블록 단위로 텍스트를 합쳐 줄바꿈을 보존한다.
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

        if not lines:
            text = self.normalize_whitespace(content_node.get_text(" ", strip=True))
            if text:
                return self.normalize_newlines(text)

            # 일부 게시글은 본문이 이미지로만 구성되어 텍스트가 비어있다.
            image_fallback = self._extract_image_only_content(content_node)
            if image_fallback:
                return image_fallback

            return ""

        text = "\n".join(lines)
        return self.normalize_newlines(text)

    def _extract_image_only_content(self, content_node: Tag) -> str:
        image_count = 0
        image_alts: list[str] = []

        for img in content_node.select("img"):
            image_count += 1
            alt = self.normalize_whitespace((img.get("alt") or "").replace("\xa0", " "))
            if alt:
                image_alts.append(alt)

        if image_alts:
            deduped = list(dict.fromkeys(image_alts))
            lines = [f"[이미지] {alt}" for alt in deduped[:10]]
            if len(deduped) > 10:
                lines.append(f"... 외 {len(deduped) - 10}개")
            return "\n".join(lines)

        if image_count > 0:
            return f"[이미지 본문] 텍스트 본문 없음 (이미지 {image_count}개)"

        return ""

    def _extract_published_at(self, soup: BeautifulSoup) -> str | None:
        # 작성일은 div.view_header 내 li.date 텍스트(예: 작성일2026-04-07)로 노출된다.
        date_node = soup.select_one("div.view_header li.date")
        if not date_node:
            return None

        date_text = date_node.get_text(" ", strip=True)
        match = re.search(r"(\d{4}[./-]\d{1,2}[./-]\d{1,2})", date_text)
        if not match:
            return None

        raw_date = match.group(1).replace(".", "-").replace("/", "-")
        year, month, day = raw_date.split("-")
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

    def _extract_category(self, soup: BeautifulSoup) -> str | None:
        # 게시판명은 breadcrumb(location) 마지막 li에서 추출한다.
        location_items = [
            item.get_text(strip=True)
            for item in soup.select("div.location_wrap ul.location li")
            if item.get_text(strip=True)
        ]

        if not location_items:
            return None

        for item in reversed(location_items):
            if item != "홈":
                return item
        return None

    def _extract_attachments(self, soup: BeautifulSoup, detail_url: str) -> list[dict]:
        attachments: list[dict] = []

        # 첨부파일 링크는 li.attatch 내부 a 태그에 연속으로 배치된다.
        attachment_container = soup.select_one("div.view_header li.attatch")
        if not attachment_container:
            return attachments

        for link in attachment_container.select("a[href]"):
            href = (link.get("href") or "").strip()
            if not href:
                continue

            absolute_url = urljoin(detail_url, href)
            name = (
                (link.get("download") or "").strip()
                or link.get_text(strip=True)
                or urlparse(absolute_url).path.split("/")[-1]
            )

            attachments.append(
                {
                    "name": self.normalize_whitespace(name),
                    "url": absolute_url,
                }
            )

        deduped: list[dict] = []
        seen_urls: set[str] = set()
        for item in attachments:
            url = item["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)
            deduped.append(item)

        return deduped
