from datetime import date

from app.schemas import Notice
from app.search import (
    expand_search_terms,
    extract_search_terms,
    filter_notices,
    rank_notices,
    recency_boost,
    score_notice,
)


def make_notice(
    notice_id: str,
    title: str,
    *,
    content: str = "본문",
    source: str = "한국항공대학교 공식 홈페이지",
    category: str | None = None,
    date: str = "2026-04-20",
) -> Notice:
    return Notice(
        id=notice_id,
        title=title,
        content=content,
        source=source,
        sources=[source],
        category=category,
        date=date,
        tags=[category] if category else [],
        attachments=[],
    )


def test_extract_search_terms_removes_request_words() -> None:
    assert extract_search_terms("공모전 정보 알려줘") == ["공모전"]


def test_filter_notices_uses_multi_term_threshold() -> None:
    notices = [
        make_notice("a", "국제 공모전 안내", content="참가자 모집"),
        make_notice("b", "수강신청 안내", content="학사 일정"),
    ]

    result = filter_notices(notices, q="국제 공모전 정보 알려줘")

    assert [notice.id for notice in result] == ["a"]


def test_rank_notices_prioritizes_relevance_then_date() -> None:
    notices = [
        make_notice("old", "일반 안내", content="수강신청", date="2026-04-23"),
        make_notice("title", "수강신청 안내", content="본문", date="2026-04-20"),
    ]

    ranked = rank_notices(notices, "수강신청", today=date(2026, 4, 24))

    assert [item.notice.id for item in ranked] == ["title", "old"]


def test_recency_boost_tiers() -> None:
    today = date(2026, 5, 15)
    assert recency_boost("2026-05-10", today) == 5
    assert recency_boost("2026-04-20", today) == 3
    assert recency_boost("2026-03-01", today) == 1
    assert recency_boost("2025-12-01", today) == 0
    assert recency_boost("2024-01-01", today) == -2


def test_score_notice_recency_only_applies_when_matched() -> None:
    today = date(2026, 5, 15)
    matched = make_notice("m", "수강신청 안내", content="본문", date="2026-05-10")
    unmatched = make_notice("u", "다른 공지", content="본문", date="2026-05-10")

    matched_score = score_notice(matched, ["수강신청"], today=today)
    unmatched_score = score_notice(unmatched, ["수강신청"], today=today)

    assert matched_score >= 5
    assert unmatched_score == 0


def test_rank_notices_recency_boost_pushes_fresh_match_up() -> None:
    today = date(2026, 5, 15)
    fresh = make_notice(
        "fresh",
        "장학금 안내",
        content="본문",
        date="2026-05-12",
    )
    old = make_notice(
        "old",
        "장학금 안내",
        content="장학금 정책 정리",
        date="2024-01-10",
    )

    ranked = rank_notices([old, fresh], "장학금", today=today)

    assert [item.notice.id for item in ranked] == ["fresh", "old"]


def test_expand_search_terms_maps_exam_colloquial_synonyms() -> None:
    # "기말고사"는 공지에 쓰인 "기말시험"의 부분문자열이 아니어서 동의어 확장이 없으면
    # 검색에 잡히지 않는다. 좁은 전용 군으로 "기말시험"에만 매핑한다(일반 "시험" 제외).
    expanded = expand_search_terms(["기말고사"])
    assert "기말시험" in expanded
    assert "시험" not in expanded  # tangential 시험 공지 차단

    expanded_mid = expand_search_terms(["중간고사"])
    assert "중간시험" in expanded_mid
    assert "시험" not in expanded_mid


def test_expand_search_terms_keeps_unrelated_terms_untouched() -> None:
    # 동의어군에 없는 term은 그대로 두고 군 확장을 일으키지 않는다.
    assert expand_search_terms(["수강신청"]) == ["수강신청"]

