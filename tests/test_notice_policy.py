from datetime import date

from app.crawler.policies.notice_policy import (
    evaluate_recent_policy,
    recent_stop_reason,
    should_prune_stale_notice,
)


TODAY = date(2026, 4, 30)
SINCE = date(2023, 1, 1)


def _decide(
    published_at: str,
    *,
    permanent: bool = False,
    since: date | None = SINCE,
) -> tuple[bool, bool]:
    decision = evaluate_recent_policy(
        board_name="테스트",
        detail_url="https://example.com/1",
        source_page=1,
        is_permanent_notice=permanent,
        published_at=published_at,
        since=since,
    )
    return decision.include_post, decision.stop_crawling


def test_since_stops_at_general_notice_posted_before_since() -> None:
    assert _decide("2022-12-31") == (False, True)


def test_since_keeps_notice_posted_on_since_even_beyond_recent_days() -> None:
    # 일수(RECENT_NOTICE_DAYS) 기준이면 멈출 게시일이지만 since가 있으면 since가 경계다.
    assert _decide("2023-01-01", since=None) == (False, True)
    assert _decide("2023-01-01") == (True, False)


def test_since_keeps_old_permanent_notice() -> None:
    assert _decide("2019-03-02", permanent=True) == (True, False)


def test_recent_stop_reason_names_since_date() -> None:
    assert recent_stop_reason(SINCE) == "since 이전 도달(since=2023-01-01)"
    assert recent_stop_reason(None) == "일반공지 1년 초과"


def test_prunes_general_notice_on_cutoff_date() -> None:
    assert should_prune_stale_notice(
        {"published_at": "2025-04-30", "is_permanent_notice": False},
        current_date=TODAY,
    )


def test_keeps_recent_general_notice() -> None:
    assert not should_prune_stale_notice(
        {"published_at": "2025-05-01", "is_permanent_notice": False},
        current_date=TODAY,
    )


def test_keeps_permanent_notice_even_when_old() -> None:
    assert not should_prune_stale_notice(
        {"published_at": "2024-04-30", "is_permanent_notice": True},
        current_date=TODAY,
    )


def test_keeps_title_duplicate_when_any_source_meta_is_recent() -> None:
    assert not should_prune_stale_notice(
        {
            "published_at": "2024-04-30",
            "source_meta": [
                {"published_at": "2024-04-30", "is_permanent_notice": False},
                {"published_at": "2026-04-01", "is_permanent_notice": False},
            ],
        },
        current_date=TODAY,
    )
