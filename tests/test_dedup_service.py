from datetime import date

from app.crawler.services.dedup_service import merge_posts_with_dedup, prune_stale_posts


TODAY = date(2026, 4, 30)


def make_post(
    post_id: str,
    *,
    title: str,
    published_at: str,
    is_permanent_notice: bool = False,
) -> dict:
    return {
        "id": post_id,
        "title": title,
        "content": "본문",
        "original_url": f"https://example.com/{post_id}",
        "source_name": "source",
        "source_type": "type",
        "category_raw": "category",
        "published_at": published_at,
        "crawled_at": "2026-04-30T00:00:00+00:00",
        "attachments": [],
        "is_permanent_notice": is_permanent_notice,
    }


def test_prune_stale_posts_removes_only_stale_general_notices() -> None:
    posts = [
        make_post("old", title="오래된 공지", published_at="2025-04-30"),
        make_post("recent", title="최근 공지", published_at="2025-05-01"),
        make_post(
            "permanent",
            title="상시 공지",
            published_at="2024-04-30",
            is_permanent_notice=True,
        ),
    ]

    result = prune_stale_posts(posts, current_date=TODAY)

    assert result.stale_pruned == 1
    assert [post["id"] for post in result.posts] == ["recent", "permanent"]


def test_title_duplicate_with_recent_source_meta_survives_pruning() -> None:
    old_post = make_post("old", title="같은 제목", published_at="2024-04-30")
    recent_post = make_post("recent", title="같은 제목", published_at="2026-04-01")

    merge_result = merge_posts_with_dedup([old_post], [recent_post])
    prune_result = prune_stale_posts(merge_result.posts, current_date=TODAY)

    assert merge_result.title_dedup_removed == 1
    assert prune_result.stale_pruned == 0
    assert [post["id"] for post in prune_result.posts] == ["old"]


def test_title_duplicate_with_permanent_source_meta_survives_pruning() -> None:
    old_post = make_post("old", title="같은 제목", published_at="2024-04-30")
    permanent_post = make_post(
        "permanent",
        title="같은 제목",
        published_at="2024-04-30",
        is_permanent_notice=True,
    )

    merge_result = merge_posts_with_dedup([old_post], [permanent_post])
    prune_result = prune_stale_posts(merge_result.posts, current_date=TODAY)

    assert merge_result.title_dedup_removed == 1
    assert prune_result.stale_pruned == 0
    assert [post["id"] for post in prune_result.posts] == ["old"]
