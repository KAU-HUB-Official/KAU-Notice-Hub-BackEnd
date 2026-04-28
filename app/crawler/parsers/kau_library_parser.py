from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlencode, urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from ..config import LIBRARY_SOURCE_NAME, LIBRARY_SOURCE_TYPE
from ..models.post import Post
from ..parsers.base_parser import BaseParser


class KAULibraryParser(BaseParser):
    """
    한국항공대학교 학술정보관(lib.kau.ac.kr) 일반공지 파서.

    HTML 구조가 변경되면 이 파일 selector를 수정한다.
    """

    def __init__(
        self,
        *,
        source_name: str = LIBRARY_SOURCE_NAME,
        source_type: str = LIBRARY_SOURCE_TYPE,
        category_fallback: str | None = None,
        base_url: str = "https://lib.kau.ac.kr",
    ) -> None:
        self.source_name = source_name
        self.source_type = source_type
        self.category_fallback = category_fallback
        self.base_url = base_url

    def parse_post_items(self, html: str, page_url: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")

        items: list[dict] = []

        # 목록 행은 onclick="go_view('4955','default_notice_view');" 패턴을 사용한다.
        for row in soup.select("tr[onclick*='go_view(']"):
            onclick = (row.get("onclick") or "").strip()
            match = re.search(r"go_view\(['\"]?(\d+)['\"]?", onclick)
            if not match:
                continue

            sb_no = match.group(1)
            params = urlencode({"sb_no": sb_no})
            classes = set(row.get("class") or [])
            marker_text = self.normalize_whitespace(row.get_text(" ", strip=True))
            is_permanent_notice = "info" in classes or "공지" in marker_text

            items.append(
                {
                    "url": urljoin(self.base_url, f"/sb/default_notice_view.mir?{params}"),
                    "is_permanent_notice": is_permanent_notice,
                }
            )

        # 구조 변경 대비 fallback: href 상세 링크 직접 수집
        if not items:
            for link in soup.select("a[href*='default_notice_view.mir'][href*='sb_no=']"):
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
            if not url:
                continue

            is_permanent_notice = bool(item.get("is_permanent_notice"))
            if url in seen_urls:
                # 동일 URL이 상시/일반 행에 중복 노출될 수 있어, 상시 플래그를 보존한다.
                if is_permanent_notice:
                    for existing in deduped:
                        if existing["url"] == url:
                            existing["is_permanent_notice"] = True
                            break
                continue

            seen_urls.add(url)
            deduped.append(
                {
                    "url": url,
                    "is_permanent_notice": is_permanent_notice,
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
        # 상세 제목은 div.sc_view_header > p.title
        node = soup.select_one("div.sc_view_header p.title")
        if not node:
            return ""
        return self.normalize_whitespace(node.get_text(" ", strip=True))

    def _extract_content_text(self, soup: BeautifulSoup) -> str:
        # 상세 본문은 div.view_content
        content_node = soup.select_one("div.view_content")
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

        image_titles: list[str] = []
        image_count = 0
        for img in content_node.select("img"):
            image_count += 1
            alt = self.normalize_whitespace(
                str(img.get("alt") or img.get("title") or "")
            )
            if alt:
                image_titles.append(alt)

        if image_titles:
            deduped = list(dict.fromkeys(image_titles))
            return "\n".join(f"[이미지] {alt}" for alt in deduped)

        if image_count > 0:
            return f"[이미지 본문] 텍스트 본문 없음 (이미지 {image_count}개)"

        return ""

    def _extract_published_at(self, soup: BeautifulSoup) -> str | None:
        # 작성일은 sc_view_header의 meta(ul > li) 내 날짜 문자열로 제공된다.
        for node in soup.select("div.sc_view_header ul li"):
            text = node.get_text(" ", strip=True)
            match = re.search(r"(\d{4}[./-]\d{1,2}[./-]\d{1,2})", text)
            if not match:
                continue
            raw = match.group(1).replace(".", "-").replace("/", "-")
            year, month, day = raw.split("-")
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

        return None

    def _extract_category(self, soup: BeautifulSoup) -> str | None:
        # 카테고리는 상단 탭/브레드크럼 텍스트가 있으면 사용하고 없으면 fallback 사용.
        for selector in [
            "section.sub_top h2",
            "section.sub_top h3",
            "div.board_title h2",
        ]:
            node = soup.select_one(selector)
            if not node:
                continue
            value = self.normalize_whitespace(node.get_text(" ", strip=True))
            if value:
                return value

        return self.category_fallback

    def _extract_attachments(self, soup: BeautifulSoup, detail_url: str) -> list[dict]:
        attachments: list[dict] = []

        # 첨부는 download_file('file_no','file_mno') onclick 패턴으로 제공된다.
        for link in soup.select("dl.sc_board dd a[onclick*='download_file(']"):
            onclick = (link.get("onclick") or "").strip()
            match = re.search(
                r"download_file\(['\"]?(\d+)['\"]?\s*,\s*['\"]?(\d+)['\"]?\)",
                onclick,
            )
            if not match:
                continue

            file_no, file_mno = match.groups()
            params = urlencode(
                {
                    "file_no": file_no,
                    "file_mno": file_mno,
                    "sb_skin": "default",
                    "sb_code": "notice",
                }
            )
            download_url = urljoin(self.base_url, f"/sb/filedownload.mir?{params}")

            name = self.normalize_whitespace(
                link.get_text(" ", strip=True) or urlparse(download_url).path.split("/")[-1]
            )
            attachments.append({"name": name, "url": download_url})

        # fallback: href 자체에 파일 다운로드 링크가 노출된 경우
        if not attachments:
            for link in soup.select("a[href*='filedownload.mir']"):
                href = (link.get("href") or "").strip()
                if not href:
                    continue
                download_url = urljoin(detail_url, href)
                name = self.normalize_whitespace(
                    link.get_text(" ", strip=True) or urlparse(download_url).path.split("/")[-1]
                )
                attachments.append({"name": name, "url": download_url})

        deduped: list[dict] = []
        seen_urls: set[str] = set()
        for item in attachments:
            if item["url"] in seen_urls:
                continue
            seen_urls.add(item["url"])
            deduped.append(item)

        return deduped
