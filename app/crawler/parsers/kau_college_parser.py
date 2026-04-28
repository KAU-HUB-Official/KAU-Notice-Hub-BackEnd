from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from ..config import COLLEGE_BASE_URL, COLLEGE_SOURCE_NAME, COLLEGE_SOURCE_TYPE
from ..models.post import Post
from ..parsers.base_parser import BaseParser


class KAUCollegeParser(BaseParser):
    """
    college.kau.ac.kr 공지(예: gc63585b) 파서.

    해당 사이트는 목록/상세를 JS API(/web/bbs/*Api.gen)로 로드하므로,
    API 응답(JSON)을 파싱한다.
    """

    def __init__(
        self,
        *,
        source_name: str = COLLEGE_SOURCE_NAME,
        source_type: str = COLLEGE_SOURCE_TYPE,
        notice_page_url: str,
        site_flag: str,
        mnu_id: str,
        bbs_id: str,
        category_raw: str | None = None,
        base_url: str = COLLEGE_BASE_URL,
    ) -> None:
        self.source_name = source_name
        self.source_type = source_type
        self.notice_page_url = notice_page_url
        self.site_flag = site_flag
        self.mnu_id = mnu_id
        self.bbs_id = bbs_id
        self.category_raw = category_raw
        self.base_url = base_url

    def parse_post_items(self, html: str, page_url: str) -> list[dict]:
        data = self._load_json(html)
        if not data:
            return []

        result_list = data.get("resultList")
        if not isinstance(result_list, list):
            return []

        items: list[dict] = []
        for item in result_list:
            if not isinstance(item, dict):
                continue

            ntt_id = str(item.get("nttId") or "").strip()
            bbs_id = str(item.get("bbsId") or self.bbs_id).strip()
            if not ntt_id:
                continue

            # gfnMoveBbsDetail 제출값과 동일한 식별자(bbsId, nttId, mnuId)를 URL로 고정한다.
            params = {
                "siteFlag": self.site_flag,
                "mnuId": self.mnu_id,
                "bbsId": bbs_id,
                "nttId": ntt_id,
                "bbsFlag": "View",
            }
            items.append(
                {
                    "url": f"{self.notice_page_url}?{urlencode(params)}",
                    "is_permanent_notice": self._is_permanent_notice(item),
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

    @staticmethod
    def _is_permanent_notice(item: dict) -> bool:
        # 대학 공통 API는 ntcYn/bnnrYn/공지기간 필드로 고정 공지를 표현한다.
        ntc_flag = str(item.get("ntcYn") or "").strip().lower()
        bnnr_flag = str(item.get("bnnrYn") or "").strip().lower()
        if ntc_flag in {"y", "yes", "true", "1"}:
            return True
        if bnnr_flag in {"y", "yes", "true", "1"}:
            return True

        ntc_no_raw = str(item.get("ntcNo") or "").strip()
        if ntc_no_raw.isdigit() and int(ntc_no_raw) > 0:
            return True

        ntce_start = str(item.get("ntceBgnde") or "").strip()
        ntce_end = str(item.get("ntceEndde") or "").strip()
        return bool(ntce_start or ntce_end)

    def parse_post(self, html: str, detail_url: str) -> Post:
        data = self._load_json(html) or {}
        result = data.get("result") if isinstance(data.get("result"), dict) else {}

        title = self.normalize_whitespace(str(result.get("nttSj") or ""))
        content_html = str(result.get("nttCn") or "")
        content = self._extract_content_text(content_html)

        published_at = self._extract_published_at(str(result.get("frstRegisterPnttm") or ""))

        attachments = self._extract_attachments(
            data.get("resultFile"),
            str(result.get("atchFileId") or "").strip(),
        )

        category_raw = (
            self.category_raw
            or self.normalize_whitespace(str(result.get("categoryCdNm") or ""))
            or self.normalize_whitespace(str(result.get("bbsNm") or ""))
            or None
        )

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

    def _load_json(self, payload: str) -> dict | None:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict):
            return data
        return None

    def _extract_content_text(self, content_html: str) -> str:
        if not content_html.strip():
            return ""

        soup = BeautifulSoup(content_html, "html.parser")

        # 본문 텍스트에서 불필요한 태그는 제거한다.
        for tag in soup(["script", "style"]):
            tag.decompose()

        for br in soup.find_all("br"):
            br.replace_with("\n")

        raw_lines = [
            self.normalize_whitespace(line)
            for line in soup.get_text("\n", strip=True).split("\n")
        ]
        lines = [line for line in raw_lines if line]

        if lines:
            return self.normalize_newlines("\n".join(lines))

        # 이미지 본문 fallback
        image_alts: list[str] = []
        image_count = 0
        for img in soup.select("img"):
            image_count += 1
            alt = self.normalize_whitespace(str(img.get("alt") or ""))
            if alt:
                image_alts.append(alt)

        if image_alts:
            deduped = list(dict.fromkeys(image_alts))
            return "\n".join(f"[이미지] {alt}" for alt in deduped)

        if image_count > 0:
            return f"[이미지 본문] 텍스트 본문 없음 (이미지 {image_count}개)"

        return ""

    def _extract_published_at(self, raw_datetime: str) -> str | None:
        match = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", raw_datetime)
        if not match:
            return None
        year, month, day = match.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

    def _extract_attachments(self, file_items: object, fallback_atch_file_id: str) -> list[dict]:
        attachments: list[dict] = []

        if not isinstance(file_items, list):
            return attachments

        for item in file_items:
            if not isinstance(item, dict):
                continue

            atch_file_id = str(item.get("atchFileId") or fallback_atch_file_id).strip()
            file_sn = str(item.get("fileSn") or "").strip()
            if not atch_file_id or not file_sn:
                continue

            params = {
                "atchFileId": atch_file_id,
                "fileSn": file_sn,
                "mnuId": self.mnu_id,
            }
            download_url = urljoin(self.base_url, f"/web/bbs/FileDownApi.gen?{urlencode(params)}")

            name = (
                self.normalize_whitespace(str(item.get("orignlFileNm") or ""))
                or self.normalize_whitespace(str(item.get("streFileNm") or ""))
                or f"attachment_{file_sn}"
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
