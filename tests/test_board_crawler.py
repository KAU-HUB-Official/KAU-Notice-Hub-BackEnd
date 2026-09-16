from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from app.crawler.models.post import Post
from app.crawler.parsers.base_parser import BaseParser
from app.crawler.parsers.kau_college_parser import KAUCollegeParser
from app.crawler.services.board_crawler import (
    STOP_EMPTY_LIST,
    STOP_REPEATED_LIST,
    STOP_REQUEST_FAILED,
    STOP_SINCE_REACHED,
    BoardAdapter,
    DetailFetchResult,
    crawl_board,
    retry_failed_details,
)

SINCE = date(2023, 1, 1)
BOARD = {"key": "test_board", "name": "테스트 공지사항"}


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

    posts, failed_items, _report = crawl_board(
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

    posts, failed_items, _report = crawl_board(
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

    posts, failed_items, _report = crawl_board(
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


def test_crawl_board_stops_before_since_and_reports_board() -> None:
    on_since_url = "https://example.com/on-since"
    before_since_url = "https://example.com/before-since"
    fetched_pages: list[int] = []
    adapter = make_adapter(
        items_by_page={
            1: [
                {"url": on_since_url, "is_permanent_notice": False},
                {"url": before_since_url, "is_permanent_notice": False},
            ],
            2: [{"url": "https://example.com/older", "is_permanent_notice": False}],
        },
        posts_by_url={
            on_since_url: make_post(on_since_url, published_at="2023-01-01"),
            before_since_url: make_post(before_since_url, published_at="2022-12-31"),
        },
        fetched_pages=fetched_pages,
        fetched_details=[],
    )

    posts, failed_items, report = crawl_board(
        BOARD, max_pages=0, adapter=adapter, known_urls=set(), since=SINCE
    )

    assert [post["original_url"] for post in posts] == [on_since_url]
    assert posts[0]["board_key"] == "test_board"
    assert failed_items == []
    assert fetched_pages == [1]
    assert (report.stop_reason, report.reached_since, report.stop_page, report.pages_read) == (
        STOP_SINCE_REACHED,
        True,
        1,
        1,
    )
    assert report.to_dict() == {
        "board_key": "test_board",
        "list_url": "https://example.com/list?page=1",
        "pages_read": 1,
        "posts": 1,
        "permanent_posts": 0,
        "oldest_published_at": "2023-01-01",
        "newest_published_at": "2023-01-01",
        "stop_reason": STOP_SINCE_REACHED,
        "stop_page": 1,
        "failed_items": 0,
        "reached_since": True,
    }


@pytest.mark.parametrize(
    "second_page, reason",
    [
        ([], STOP_EMPTY_LIST),
        ([{"url": "https://example.com/a", "is_permanent_notice": False}], STOP_REPEATED_LIST),
        (None, STOP_REQUEST_FAILED),
    ],
)
def test_crawl_board_reports_non_date_stop_reason(second_page, reason) -> None:
    url = "https://example.com/a"
    items_by_page = {1: [{"url": url, "is_permanent_notice": False}]}
    if second_page is not None:
        items_by_page[2] = second_page
    adapter = make_adapter(
        items_by_page=items_by_page,
        posts_by_url={url: make_post(url, published_at="2026-05-01")},
        fetched_pages=[],
        fetched_details=[],
    )

    _posts, _failed_items, report = crawl_board(
        BOARD, max_pages=0, adapter=adapter, known_urls=set(), since=SINCE
    )

    assert (report.stop_reason, report.stop_page, report.pages_read, report.reached_since) == (
        reason,
        2,
        1,
        False,
    )


def test_crawl_board_drops_notice_with_no_title_or_content() -> None:
    """본문·이미지·첨부가 모두 없는 공지는 읽을 내용이 없어 연구 수집에서도 남기지 않는다."""
    url = "https://example.com/title-only"
    title_only = replace(make_post(url, title="학점교류 수강안내"), content="")
    adapter = make_adapter(
        items_by_page={1: [{"url": url, "is_permanent_notice": False}]},
        posts_by_url={url: title_only},
        fetched_pages=[],
        fetched_details=[],
    )

    posts, failed_items, _report = crawl_board(
        BOARD, max_pages=0, adapter=adapter, known_urls=set(), since=SINCE
    )

    assert posts == []
    assert [item["reason"] for item in failed_items] == ["required_field_empty:content"]


def test_college_body_images_ignore_previous_and_next_articles() -> None:
    """college 상세 API는 이전·다음 글 본문도 함께 주므로 그 글의 이미지가 이 공지에 붙으면 안 된다."""
    other = {"nttCn": '<p><img src="/web/cmm/imageSrc.do?path=next-article-poster"></p>'}
    details = {
        "1": {"nttSj": "수강신청 안내", "frstRegisterPnttm": "2026-07-23", "nttCn": '<p>안내</p><img src="/web/cmm/imageSrc.do?path=own">'},
        "2": {"nttSj": "본문이 빈 공지", "frstRegisterPnttm": "2026-07-23", "nttCn": ""},
    }
    parser = KAUCollegeParser(
        notice_page_url="http://college.kau.ac.kr/web/pages/gc1986b.do", site_flag="am_www", mnu_id="gc1986b", bbs_id="0024"
    )

    def fetch_detail(board: dict, detail_url: str) -> DetailFetchResult:
        ntt_id = parse_qs(urlparse(detail_url).query)["nttId"][0]
        return DetailFetchResult(
            html=json.dumps({"result": details[ntt_id], "resultPre": other, "resultPost": other, "resultFile": []})
        )

    adapter = BoardAdapter(
        parser_factory=lambda board: parser,
        build_list_page_url=lambda board, page: board["key"],
        fetch_list_html=lambda board, page: json.dumps({"resultList": [{"nttId": "1"}, {"nttId": "2"}]}) if page == 1 else None,
        fetch_detail=fetch_detail,
    )

    posts, failed_items, _report = crawl_board(
        BOARD, max_pages=0, adapter=adapter, known_urls=set(), since=SINCE
    )

    # 이웃 글 이미지를 가져오지 않으므로, 본문이 빈 공지는 이미지가 붙지 않아 그대로 버려진다.
    assert [post["title"] for post in posts] == ["수강신청 안내"]
    assert [a["url"] for a in posts[0]["content_assets"]] == [
        "http://college.kau.ac.kr/web/cmm/imageSrc.do?path=own"
    ]
    assert [item["reason"] for item in failed_items] == ["required_field_empty:content"]


def test_retry_failed_details_recovers_transient_detail_failure() -> None:
    url = "https://example.com/flaky"
    attempts: list[str] = []
    parser = FakeParser({1: [{"url": url, "is_permanent_notice": False}]}, {url: make_post(url)})

    def fetch_detail(board: dict, detail_url: str) -> DetailFetchResult:
        attempts.append(detail_url)
        return DetailFetchResult(html="<html></html>" if len(attempts) > 1 else None)

    adapter = BoardAdapter(
        parser_factory=lambda board: parser,
        build_list_page_url=lambda board, page: f"https://example.com/list?page={page}",
        fetch_list_html=lambda board, page: str(page) if page == 1 else None,
        fetch_detail=fetch_detail,
    )

    posts, failed_items, report = crawl_board(
        BOARD, max_pages=0, adapter=adapter, known_urls=set(), since=SINCE
    )
    assert posts == []
    assert [item["reason"] for item in failed_items] == ["request_failed"]
    assert report.failed_items == 1

    result = retry_failed_details(
        BOARD, report, adapter=adapter, known_urls=set(), known_posts_by_url={}, since=SINCE
    )

    assert result.attempted_urls == [url]
    assert [post["original_url"] for post in result.recovered] == [url]
    assert result.still_failed == []
