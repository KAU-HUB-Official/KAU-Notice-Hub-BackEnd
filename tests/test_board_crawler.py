from __future__ import annotations

from app.crawler.models.post import Post
from app.crawler.parsers.base_parser import BaseParser
from app.crawler.services.board_crawler import BoardAdapter, DetailFetchResult, crawl_board


class FakeParser(BaseParser):
    def __init__(self, items_by_page: dict[int, list[dict]], posts_by_url: dict[str, Post]) -> None:
        self.items_by_page = items_by_page
        self.posts_by_url = posts_by_url

    def parse_post_urls(self, html: str, page_url: str) -> list[str]:
        return [str(item["url"]) for item in self.parse_post_items(html, page_url)]

    def parse_post_items(self, html: str, page_url: str) -> list[dict]:
        return self.items_by_page[int(html)]

    def parse_post(self, html: str, detail_url: str) -> Post:
        return self.posts_by_url[detail_url]


def make_post(url: str, *, title: str = "새 공지", published_at: str = "2026-05-01") -> Post:
    return Post(
        source_name="테스트",
        source_type="test",
        category_raw="테스트",
        title=title,
        content="본문입니다.",
        published_at=published_at,
        original_url=url,
        attachments=[],
        crawled_at="2026-05-10T00:00:00+00:00",
    )


def make_adapter(
    *,
    items_by_page: dict[int, list[dict]],
    posts_by_url: dict[str, Post] | None = None,
    fetched_pages: list[int],
    fetched_details: list[str],
) -> BoardAdapter:
    parser = FakeParser(items_by_page, posts_by_url or {})

    def fetch_list_html(board: dict, page: int) -> str | None:
        fetched_pages.append(page)
        return str(page) if page in items_by_page else None

    def fetch_detail(board: dict, detail_url: str) -> DetailFetchResult:
        fetched_details.append(detail_url)
        return DetailFetchResult(html="<html></html>")

    return BoardAdapter(
        parser_factory=lambda board: parser,
        build_list_page_url=lambda board, page: f"https://example.com/list?page={page}",
        fetch_list_html=fetch_list_html,
        fetch_detail=fetch_detail,
    )


def test_crawl_board_stops_when_page_has_no_new_general_items() -> None:
    known_url = "https://example.com/known"
    fetched_pages: list[int] = []
    fetched_details: list[str] = []
    adapter = make_adapter(
        items_by_page={
            1: [{"url": known_url, "is_permanent_notice": False}],
            2: [{"url": "https://example.com/new", "is_permanent_notice": False}],
        },
        fetched_pages=fetched_pages,
        fetched_details=fetched_details,
    )

    posts, failed_items = crawl_board(
        {"key": "test_board", "name": "테스트 공지사항"},
        max_pages=0,
        adapter=adapter,
        known_urls={known_url},
        known_posts_by_url={known_url: {"published_at": "2026-05-01"}},
    )

    assert posts == []
    assert failed_items == []
    assert fetched_pages == [1]
    assert fetched_details == []


def test_crawl_board_collects_new_permanent_item_before_no_new_general_stop() -> None:
    known_url = "https://example.com/known"
    permanent_url = "https://example.com/permanent"
    fetched_pages: list[int] = []
    fetched_details: list[str] = []
    adapter = make_adapter(
        items_by_page={
            1: [
                {"url": permanent_url, "is_permanent_notice": True},
                {"url": known_url, "is_permanent_notice": False},
            ],
            2: [{"url": "https://example.com/new", "is_permanent_notice": False}],
        },
        posts_by_url={permanent_url: make_post(permanent_url, title="상시 공지")},
        fetched_pages=fetched_pages,
        fetched_details=fetched_details,
    )

    posts, failed_items = crawl_board(
        {"key": "test_board", "name": "테스트 공지사항"},
        max_pages=0,
        adapter=adapter,
        known_urls={known_url},
        known_posts_by_url={known_url: {"published_at": "2026-05-01"}},
    )

    assert [post["original_url"] for post in posts] == [permanent_url]
    assert posts[0]["is_permanent_notice"] is True
    assert failed_items == []
    assert fetched_pages == [1]
    assert fetched_details == [permanent_url]


def test_crawl_board_continues_when_page_has_only_known_permanent_items() -> None:
    known_permanent_url = "https://example.com/permanent"
    new_general_url = "https://example.com/new"
    fetched_pages: list[int] = []
    fetched_details: list[str] = []
    adapter = make_adapter(
        items_by_page={
            1: [{"url": known_permanent_url, "is_permanent_notice": True}],
            2: [{"url": new_general_url, "is_permanent_notice": False}],
        },
        posts_by_url={new_general_url: make_post(new_general_url, title="새 일반 공지")},
        fetched_pages=fetched_pages,
        fetched_details=fetched_details,
    )

    posts, failed_items = crawl_board(
        {"key": "test_board", "name": "테스트 공지사항"},
        max_pages=2,
        adapter=adapter,
        known_urls={known_permanent_url},
        known_posts_by_url={known_permanent_url: {"published_at": "2026-05-01"}},
    )

    assert [post["original_url"] for post in posts] == [new_general_url]
    assert posts[0]["is_permanent_notice"] is False
    assert failed_items == []
    assert fetched_pages == [1, 2]
    assert fetched_details == [new_general_url]
