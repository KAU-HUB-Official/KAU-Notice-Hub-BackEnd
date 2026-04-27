from app.schemas import Notice
from app.search import extract_search_terms, filter_notices, rank_notices


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
        summary=content,
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

    ranked = rank_notices(notices, "수강신청")

    assert [item.notice.id for item in ranked] == ["title", "old"]

