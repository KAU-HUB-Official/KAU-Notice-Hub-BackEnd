"""연구용 원본 수집(--research) 검증 — 네트워크 호출 없음.

가짜 게시판 두 개로 같은 제목 회차 보존, 게시판 간 URL 중복 제거, 본문 빈 공지 보존, 실패 재시도,
게시판별 수집 기록, 운영 결과 파일 미사용을 확인한다.
"""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest

from app.crawler import main as crawler_main
from app.crawler.models.post import Post
from app.crawler.parsers.base_parser import BaseParser
from app.crawler.services.board_crawler import BoardAdapter, DetailFetchResult

SINCE = date(2023, 1, 1)
BOARDS = [
    {"key": "board_a", "name": "A학과 공지사항", "board_type": "fake"},
    {"key": "board_b", "name": "B학과 공지사항", "board_type": "fake"},
]
URL_2026 = "https://example.com/a/2026"
URL_2025 = "https://example.com/a/2025"
URL_BEFORE_SINCE = "https://example.com/a/2022"
URL_FLAKY = "https://example.com/b/flaky"
URL_TITLE_ONLY = "https://example.com/b/title-only"
# 목록 페이지 → 공지 URL. B학과 1쪽의 URL_2026은 A학과와 같은 URL로 올라온 공지다.
LIST_PAGES = {
    "board_a:1": [URL_2026, URL_2025],
    "board_a:2": [URL_BEFORE_SINCE],
    "board_b:1": [URL_2026, URL_FLAKY, URL_TITLE_ONLY],
    "board_b:2": [],
}


def _post(url: str, title: str, published_at: str, content: str = "본문입니다.") -> Post:
    return Post(
        source_name="테스트학과",
        source_type="department",
        category_raw="공지",
        title=title,
        content=content,
        published_at=published_at,
        original_url=url,
        attachments=[],
        crawled_at="2026-09-15T00:00:00+09:00",
    )


class FakeParser(BaseParser):
    def __init__(self, posts_by_url: dict[str, Post]) -> None:
        self.posts_by_url = posts_by_url

    def parse_post_urls(self, html: str, page_url: str) -> list[str]:
        return [str(item["url"]) for item in self.parse_post_items(html, page_url)]

    def parse_post_items(self, html: str, page_url: str) -> list[dict]:
        return [{"url": url, "is_permanent_notice": False} for url in LIST_PAGES[html]]

    def parse_post(self, html: str, detail_url: str) -> Post:
        return self.posts_by_url[detail_url]


def _fake_adapter() -> BoardAdapter:
    parser = FakeParser(
        {
            URL_2026: _post(URL_2026, "유고결석 신청 관련 공지", "2026-03-31"),
            URL_2025: _post(URL_2025, "유고결석 신청 관련 공지", "2025-04-01"),
            URL_BEFORE_SINCE: _post(URL_BEFORE_SINCE, "오래된 공지", "2022-12-31"),
            URL_FLAKY: _post(URL_FLAKY, "처음엔 실패하는 공지", "2026-05-01"),
            URL_TITLE_ONLY: _post(URL_TITLE_ONLY, "제목만 있는 공지", "2026-04-01", content=""),
        }
    )
    flaky_attempts: list[str] = []

    def fetch_list_html(board: dict, page: int) -> str | None:
        key = f"{board['key']}:{page}"
        return key if key in LIST_PAGES else None

    def fetch_detail(board: dict, detail_url: str) -> DetailFetchResult:
        if detail_url == URL_FLAKY:
            flaky_attempts.append(detail_url)
            if len(flaky_attempts) == 1:
                return DetailFetchResult(html=None)
        return DetailFetchResult(html="<html></html>")

    return BoardAdapter(
        parser_factory=lambda board: parser,
        build_list_page_url=lambda board, page: f"https://example.com/{board['key']}?page={page}",
        fetch_list_html=fetch_list_html,
        fetch_detail=fetch_detail,
    )


@pytest.fixture
def research_env(monkeypatch, tmp_path):
    adapter = _fake_adapter()
    monkeypatch.setattr(crawler_main, "NOTICE_BOARDS", BOARDS)
    monkeypatch.setattr(crawler_main, "build_clients", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(crawler_main, "build_board_adapters", lambda clients: {"fake": adapter})
    monkeypatch.setattr(
        crawler_main, "_git_state", lambda: {"commit": "abc123", "uncommitted_files": 0}
    )
    monkeypatch.setattr(crawler_main, "FAILED_OUTPUT_FILE", tmp_path / "production_failed.json")

    def must_not_run(*args, **kwargs):
        raise AssertionError("연구 수집에서는 호출되면 안 된다")

    monkeypatch.setattr(crawler_main, "prune_stale_posts", must_not_run)
    monkeypatch.setattr(
        crawler_main, "ContentEnrichmentService", SimpleNamespace(from_settings=must_not_run)
    )
    return tmp_path


def test_research_crawl_keeps_repeats_and_writes_manifest(research_env) -> None:
    out = research_env / "research" / "kau_notices_raw_2026-09-15.json"
    manifest_path = research_env / "research" / "crawl_manifest_2026-09-15.json"

    crawler_main.crawl_all_notices(
        0,
        out,
        since=SINCE,
        research=True,
        manifest_path=manifest_path,
        command="python -m app.crawler.main --research",
    )

    saved = json.loads(out.read_text(encoding="utf-8"))
    by_url = {post["original_url"]: post for post in saved}
    # 제목이 같은 두 해의 회차가 모두 남는다.
    assert sorted(
        post["published_at"] for post in saved if post["title"] == "유고결석 신청 관련 공지"
    ) == ["2025-04-01", "2026-03-31"]
    # 두 게시판에 같은 URL로 올라온 공지는 1건이고, 먼저 수집한 게시판으로 남는다.
    assert sorted(by_url) == sorted([URL_2026, URL_2025, URL_FLAKY, URL_TITLE_ONLY])
    assert by_url[URL_2026]["board_key"] == "board_a"
    assert all(
        isinstance(post["source_name"], str) and isinstance(post["category_raw"], str)
        for post in saved
    )
    assert (by_url[URL_TITLE_ONLY]["content"], by_url[URL_TITLE_ONLY]["content_empty"]) == ("", True)

    # 실패 목록은 원본 옆에 두고, 운영 실패 파일은 건드리지 않는다.
    failed_path = out.with_name("kau_notices_raw_2026-09-15.failed.json")
    assert json.loads(failed_path.read_text(encoding="utf-8")) == []
    assert not (research_env / "production_failed.json").exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["git"] == {"commit": "abc123", "uncommitted_files": 0}
    assert manifest["command"] == "python -m app.crawler.main --research"
    assert manifest["options"]["since"] == "2023-01-01"
    assert (manifest["totals"]["title_dedup_removed"], manifest["totals"]["content_empty_posts"]) == (0, 1)
    assert manifest["retry"] == {"attempted": 1, "recovered": [URL_FLAKY], "still_failed": []}

    boards = {board["board_key"]: board for board in manifest["boards"]}
    assert (
        boards["board_a"]["stop_reason"],
        boards["board_a"]["stop_page"],
        boards["board_a"]["oldest_published_at"],
    ) == ("since_reached", 2, "2025-04-01")
    assert (
        boards["board_b"]["stop_reason"],
        boards["board_b"]["posts"],
        boards["board_b"]["failed_items"],
        boards["board_b"]["oldest_published_at"],
    ) == ("empty_list", 2, 0, "2026-04-01")
    # B학과는 빈 목록으로 멈췄고 가장 오래된 공지가 since보다 90일 넘게 늦어 확인 대상이다.
    assert [board["board_key"] for board in manifest["review_boards"]] == ["board_b"]


def test_research_crawl_refuses_existing_raw_and_dirty_tree(research_env, monkeypatch) -> None:
    existing = research_env / "raw.json"
    existing.write_text("[]", encoding="utf-8")
    with pytest.raises(FileExistsError):
        crawler_main.crawl_all_notices(0, existing, since=SINCE, research=True)

    monkeypatch.setattr(
        crawler_main, "_git_state", lambda: {"commit": "abc123", "uncommitted_files": 1}
    )
    with pytest.raises(RuntimeError, match="미커밋"):
        crawler_main.crawl_all_notices(0, research_env / "new.json", since=SINCE, research=True)
    assert not (research_env / "new.json").exists()


def test_research_flag_requires_since() -> None:
    with pytest.raises(SystemExit):
        crawler_main.parse_args(["--research", "--output", "raw.json"])

    args = crawler_main.parse_args(["--research", "--since", "2023-01-01", "--output", "raw.json"])
    assert (args.research, args.since) == (True, SINCE)
