"""이미 수집한 공지가 게시판에서 수정됐는지 확인하고 반영한다.

수집한 공지는 URL이 같으면 다시 열지 않아 게시 후 수정한 내용이 사이트에 반영되지 않았다.
최근 공지와 상시공지만 상세 페이지를 다시 읽어, 파싱한 원문의 해시가 저장된 해시와 다르면 갱신한다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..policies.notice_policy import parse_published_date

# 원문을 새로 파싱해 덮어쓰는 필드. 출처·분류(제목 중복 병합 시 배열로 쌓임)·상시공지 여부처럼
# 수집 과정에서 쌓인 값은 두고, 게시판에서 작성자가 고칠 수 있는 값만 바꾼다.
UPDATED_FIELDS: tuple[str, ...] = (
    "title",
    "content",
    "published_at",
    "content_assets",
    "crawled_at",
    "content_hash",
)


def compute_content_hash(post: dict) -> str:
    """보강 전 원문(제목·본문·첨부) 기준 sha256.

    본문 보강이 content를 바꿔도 비교가 흔들리지 않도록 파싱 직후 값으로 계산해 저장한다.
    """
    attachments = [
        [str(item.get("name") or ""), str(item.get("url") or "")]
        for item in post.get("attachments") or []
        if isinstance(item, dict)
    ]
    payload = json.dumps(
        [str(post.get("title") or ""), str(post.get("content") or ""), attachments],
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class RecheckPolicy:
    """게시일이 최근 days일 이내인 기존 공지와 상시공지를 다시 읽는다. done_urls는 한 번 수집에서 공유한다.

    상시공지는 게시일이 오래돼도 내용을 자주 고치므로 날짜와 무관하게 매 수집마다 확인한다.
    """

    days: int
    today: date = field(default_factory=date.today)
    done_urls: set[str] = field(default_factory=set)

    def should_recheck(self, detail_url: str, known_post: dict | None) -> bool:
        # source_meta 항목(제목 중복으로 합쳐진 다른 게시판 URL)은 공지 본체가 아니라 건너뛴다.
        if not known_post or known_post.get("original_url") != detail_url or "content" not in known_post:
            return False
        if detail_url in self.done_urls:
            return False
        if known_post.get("is_permanent_notice"):
            return True
        published = parse_published_date(known_post.get("published_at"))
        return published is not None and published >= self.today - timedelta(days=self.days)


def apply_notice_update(existing: dict, fresh: dict) -> None:
    """수정된 공지를 기존 항목에 반영한다.

    본문이 바뀌었으니 이전 보강 결과는 지워 다음 보강 단계가 새 원문으로 다시 판단하게 한다.
    첨부는 제목 중복으로 합쳐진 공지면 다른 게시판에서 온 첨부가 섞여 있어 새 첨부에 없는
    기존 첨부를 남기고, 아니면 새 첨부로 바꾼다.
    """
    for key in UPDATED_FIELDS:
        if key in fresh:
            existing[key] = fresh[key]
    existing.pop("content_original", None)
    existing.pop("content_enrichment", None)

    fresh_attachments = list(fresh.get("attachments") or [])
    source_meta = existing.get("source_meta")
    if isinstance(source_meta, list) and len(source_meta) > 1:
        fresh_urls = {item.get("url") for item in fresh_attachments if isinstance(item, dict)}
        fresh_attachments += [
            item
            for item in existing.get("attachments") or []
            if isinstance(item, dict) and item.get("url") not in fresh_urls
        ]
    existing["attachments"] = fresh_attachments
