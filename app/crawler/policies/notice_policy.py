from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from ..config import RECENT_NOTICE_DAYS
from ..utils.logger import get_logger

logger = get_logger("crawler.policies.notice_policy")


@dataclass(frozen=True)
class RecentPolicyDecision:
    include_post: bool
    stop_crawling: bool


def parse_published_date(published_at: str | None) -> date | None:
    if not published_at:
        return None

    # 파서별 포맷(YYYY-MM-DD, YYYY.MM.DD, YYYY-MM-DD HH:MM 등)에서 날짜만 추출한다.
    match = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", str(published_at))
    if not match:
        return None

    year, month, day = (int(value) for value in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _cutoff_date(*, lookback_days: int, current_date: date | None = None) -> date:
    return (current_date or date.today()) - timedelta(days=lookback_days)


def _field(post: dict[str, Any], name: str) -> Any:
    return post.get(name)


def _iter_published_values(post: dict[str, Any]) -> list[Any]:
    values = [
        _field(post, "published_at"),
        _field(post, "date"),
        _field(post, "created_at"),
        _field(post, "updated_at"),
    ]

    source_meta = post.get("source_meta")
    if isinstance(source_meta, list):
        for meta in source_meta:
            if isinstance(meta, dict):
                values.append(meta.get("published_at"))
                values.append(meta.get("date"))

    return values


def _has_permanent_notice_meta(post: dict[str, Any]) -> bool:
    source_meta = post.get("source_meta")
    if not isinstance(source_meta, list) or not source_meta:
        return bool(post.get("is_permanent_notice"))

    return any(
        isinstance(meta, dict) and bool(meta.get("is_permanent_notice"))
        for meta in source_meta
    )


def should_prune_stale_notice(
    post: dict[str, Any],
    *,
    lookback_days: int = RECENT_NOTICE_DAYS,
    current_date: date | None = None,
) -> bool:
    if _has_permanent_notice_meta(post):
        return False

    published_dates = [
        parsed_date
        for value in _iter_published_values(post)
        if (parsed_date := parse_published_date(str(value) if value is not None else None))
    ]
    if not published_dates:
        return False

    cutoff_date = _cutoff_date(lookback_days=lookback_days, current_date=current_date)
    return all(published_date <= cutoff_date for published_date in published_dates)


def evaluate_recent_policy(
    *,
    board_name: str,
    detail_url: str,
    source_page: int,
    is_permanent_notice: bool,
    published_at: str | None,
) -> RecentPolicyDecision:
    """
    Returns:
      - include_post: 결과 저장 여부
      - stop_crawling: 현재 게시판 상세 수집 루프 중단 여부
    """
    if is_permanent_notice:
        # 상시 공지는 작성일과 무관하게 모두 수집한다.
        return RecentPolicyDecision(include_post=True, stop_crawling=False)

    # 일반 공지는 게시일이 1년을 초과한 경우에만 수집을 중단한다.
    published_date = parse_published_date(published_at)
    cutoff_date = _cutoff_date(lookback_days=RECENT_NOTICE_DAYS)

    if published_date and published_date <= cutoff_date:
        # 일반 공지에서 1년 전 이상을 만나면 해당 보드 상세 수집을 종료한다.
        logger.debug(
            "수집 종료 후보 | 게시판=%s | 사유=일반공지 1년 초과 | 게시일=%s | 페이지=%s | url=%s",
            board_name,
            published_at,
            source_page,
            detail_url,
        )
        return RecentPolicyDecision(include_post=False, stop_crawling=True)

    return RecentPolicyDecision(include_post=True, stop_crawling=False)
