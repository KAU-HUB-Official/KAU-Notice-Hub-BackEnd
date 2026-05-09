from datetime import date

from app.crawler.policies.notice_policy import should_prune_stale_notice


TODAY = date(2026, 4, 30)


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
