from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from ..config import CAREER_SOURCE_NAME, CAREER_SOURCE_TYPE
from ..models.post import Post
from ..parsers.base_parser import BaseParser


class KAUCareerParser(BaseParser):
    """
    한국항공대학교 대학일자리플러스센터(취업공지) 파서.

    HTML 구조가 변경되면 이 파일의 selector를 수정한다.
    """

    def __init__(
        self,
        *,
        source_name: str = CAREER_SOURCE_NAME,
        source_type: str = CAREER_SOURCE_TYPE,
    ) -> None:
        self.source_name = source_name
        self.source_type = source_type

    def parse_post_items(self, html: str, page_url: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")

        items: list[dict] = []

        # 목록은 ul[data-role='table'] > li.tbody 단위이며 li.tbody.notice가 상시 공지다.
        for row in soup.select("ul[data-role='table'] li.tbody"):
            link = row.select_one("span.title > a[href]")
            if not link:
                continue

            href = (link.get("href") or "").strip()
            if not href:
                continue
            absolute_url = urljoin(page_url, href)
            if "/view/" not in absolute_url:
                continue

            classes = set(row.get("class") or [])
            is_permanent_notice = "notice" in classes
            if not is_permanent_notice:
                loopnum = row.select_one("span.loopnum")
                marker_text = self.normalize_whitespace(loopnum.get_text(" ", strip=True) if loopnum else "")
                is_permanent_notice = "공지" in marker_text or "notice" in marker_text.lower()

            items.append(
                {
                    "url": absolute_url,
                    "is_permanent_notice": is_permanent_notice,
                }
            )

        if not items:
            for link in soup.select("a[href*='/view/'][href*='/ko/community/notice']"):
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
        # 상세 제목은 article[data-role='post'] > .header > h5
        node = soup.select_one("article[data-role='post'] .header h5")
        if not node:
            return ""
        return self.normalize_whitespace(node.get_text(" ", strip=True))

    def _extract_content_text(self, soup: BeautifulSoup) -> str:
        # 상세 본문은 .content 내부의 [data-role='wysiwyg-content'] 영역
        content_node = soup.select_one("#ModuleBoardunivBodyPrintBox [data-role='wysiwyg-content']")
        if not content_node:
            content_node = soup.select_one("article[data-role='post'] .content")
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

        if not lines:
            text = self.normalize_whitespace(content_node.get_text(" ", strip=True))
            if text:
                return self.normalize_newlines(text)

            image_count = len(content_node.select("img"))
            if image_count > 0:
                return f"[이미지 본문] 텍스트 본문 없음 (이미지 {image_count}개)"

            return ""

        return self.normalize_newlines("\n".join(lines))

    def _extract_published_at(self, soup: BeautifulSoup) -> str | None:
        # 작성일은 .header li.date time 텍스트(YYYY-MM-DD HH:MM:SS)
        node = soup.select_one("article[data-role='post'] .header li.date time")
        if not node:
            return None

        raw = node.get_text(" ", strip=True)
        match = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
        if match:
            return match.group(1)

        iso_value = (node.get("datetime") or "").strip()
        match = re.search(r"(\d{4}-\d{2}-\d{2})", iso_value)
        if match:
            return match.group(1)

        return None

    def _extract_category(self, soup: BeautifulSoup) -> str | None:
        # breadcrumb 마지막 span 또는 좌측 nav 선택 항목을 카테고리로 사용
        crumbs = [item.get_text(strip=True) for item in soup.select("div.nbreadcrumb span") if item.get_text(strip=True)]
        if crumbs:
            return crumbs[-1]

        selected = soup.select_one("section nav ul li.selected a")
        if selected:
            text = selected.get_text(strip=True)
            if text:
                return text

        return None

    def _extract_attachments(self, soup: BeautifulSoup, detail_url: str) -> list[dict]:
        attachments: list[dict] = []

        # 첨부는 data-module='attachment' 내 a[href] 링크에 들어있으며
        # 일부는 data-download, 일부는 href에 직접 다운로드 경로를 담는다.
        for link in soup.select("[data-module='attachment'] a[href]"):
            name = self.normalize_whitespace(link.get_text(" ", strip=True))
            name = re.sub(r"^\([^)]{1,20}\)\s*", "", name).strip()
            raw_url = (link.get("data-download") or link.get("href") or "").strip()
            if not raw_url:
                continue
            absolute_url = urljoin(detail_url, raw_url)
            attachments.append({"name": name, "url": absolute_url})

        deduped: list[dict] = []
        seen: set[str] = set()
        for item in attachments:
            if item["url"] in seen:
                continue
            seen.add(item["url"])
            deduped.append(item)

        return deduped
