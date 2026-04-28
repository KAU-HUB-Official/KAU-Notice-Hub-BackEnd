from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlencode, urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from ..config import ADMISSION_SOURCE_NAME, ADMISSION_SOURCE_TYPE
from ..models.post import Post
from ..parsers.base_parser import BaseParser


class KAUAdmissionParser(BaseParser):
    """
    한국항공대학교 입학처(ibhak.kau.ac.kr) 공지 파서.

    HTML 구조가 바뀌면 이 파일의 selector를 수정한다.
    """

    def __init__(
        self,
        *,
        source_name: str = ADMISSION_SOURCE_NAME,
        source_type: str = ADMISSION_SOURCE_TYPE,
        default_board_id: str = "BBS0004",
        category_fallback: str | None = None,
    ) -> None:
        self.source_name = source_name
        self.source_type = source_type
        self.default_board_id = default_board_id
        self.category_fallback = category_fallback

    def parse_post_items(self, html: str, page_url: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")

        board_id = self._extract_board_id(soup)
        current_page = self._extract_current_page(soup)
        detail_base = urljoin(page_url, "noticeView.asp")

        items: list[dict] = []

        # 목록 링크는 href 대신 onclick="viewBoardProcess('6119')" 구조를 사용한다.
        for row in soup.select("section.board_list .bl table tbody tr"):
            link = row.select_one("td.tit a[onclick]")
            if not link:
                continue

            onclick = (link.get("onclick") or "").strip()
            match = re.search(r"viewBoardProcess\(['\"]?(\d+)['\"]?\)", onclick)
            if not match:
                continue

            board_idx = match.group(1)
            params = {
                "p_board_id": board_id,
                "p_board_idx": board_idx,
                "page": current_page,
            }
            is_permanent_notice = row.select_one("td.no._important, span._important_txt") is not None
            if not is_permanent_notice:
                number_cell = row.select_one("td.no")
                marker_text = self.normalize_whitespace(number_cell.get_text(" ", strip=True) if number_cell else "")
                is_permanent_notice = bool(
                    marker_text
                    and (
                        ("공지" in marker_text)
                        or ("notice" in marker_text.lower())
                        or (not marker_text.isdigit())
                    )
                )

            items.append(
                {
                    "url": f"{detail_base}?{urlencode(params)}",
                    "is_permanent_notice": is_permanent_notice,
                }
            )

        # 구조 변경 시 직접 href 상세 링크를 fallback으로 허용한다.
        if not items:
            for link in soup.select("section.board_list .bl table tbody td.tit a[href]"):
                href = (link.get("href") or "").strip()
                if not href:
                    continue
                absolute_url = urljoin(page_url, href)
                if "noticeView.asp" not in absolute_url:
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

    def _extract_board_id(self, soup: BeautifulSoup) -> str:
        node = soup.select_one("form[name='boardForm'] input[name='p_board_id']")
        value = self.normalize_whitespace((node.get("value") or "") if node else "")
        return value or self.default_board_id

    def _extract_current_page(self, soup: BeautifulSoup) -> int:
        node = soup.select_one("form[name='boardForm'] input[name='page']")
        raw = self.normalize_whitespace((node.get("value") or "") if node else "")
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        return 1

    def _extract_title(self, soup: BeautifulSoup) -> str:
        # 상세 제목은 section.board_read > .br_top > h2.br_tit
        node = soup.select_one("section.board_read h2.br_tit")
        if not node:
            return ""
        return self.normalize_whitespace(node.get_text(" ", strip=True))

    def _extract_content_text(self, soup: BeautifulSoup) -> str:
        # 본문은 section.board_read > div.br_con > div.editor
        content_node = soup.select_one("section.board_read div.br_con .editor")
        if not content_node:
            content_node = soup.select_one("section.board_read div.br_con")
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
        # 작성일은 ul.br_info 에서 "작성일" 라벨 옆 bri_desc 값으로 제공된다.
        for item in soup.select("section.board_read ul.br_info li"):
            label = self.normalize_whitespace(
                (item.select_one(".bri_tit").get_text(" ", strip=True) if item.select_one(".bri_tit") else "")
            )
            if "작성일" not in label:
                continue
            value_node = item.select_one(".bri_desc")
            if not value_node:
                continue
            raw = value_node.get_text(" ", strip=True)
            match = re.search(r"(\d{4}[./-]\d{1,2}[./-]\d{1,2})", raw)
            if not match:
                continue
            normalized = match.group(1).replace(".", "-").replace("/", "-")
            year, month, day = normalized.split("-")
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

        return None

    def _extract_category(self, soup: BeautifulSoup) -> str | None:
        # 카테고리는 상세 상단의 h3.br_cart(예: 공통/정시/재외국민)
        node = soup.select_one("section.board_read h3.br_cart")
        if node:
            value = self.normalize_whitespace(node.get_text(" ", strip=True))
            if value:
                return value
        return self.category_fallback

    def _extract_attachments(self, soup: BeautifulSoup, detail_url: str) -> list[dict]:
        attachments: list[dict] = []

        # 첨부는 div.br_file ul.br_file_list > li > a[href] 형태로 제공된다.
        for link in soup.select("section.board_read div.br_file a[href]"):
            href = (link.get("href") or "").strip()
            if not href:
                continue

            absolute_url = urljoin(detail_url, href)
            name = self.normalize_whitespace(
                link.get_text(" ", strip=True) or urlparse(absolute_url).path.split("/")[-1]
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
