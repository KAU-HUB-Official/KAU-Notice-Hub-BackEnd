"""scripts/research/mark_crossposts.py 교차 게시 표시 규칙 검증."""

from __future__ import annotations

import json

import pytest

from scripts.research.mark_crossposts import main, mark_crossposts, summarize


def _post(url: str, title: str, published_at: str | None, board_key: str | None) -> dict:
    return {
        "original_url": f"https://example.com/{url}",
        "title": title,
        "published_at": published_at,
        "board_key": board_key,
    }


def _groups(marked: list[dict]) -> dict[str, str | None]:
    return {post["original_url"].rsplit("/", 1)[-1]: post["crosspost_group_id"] for post in marked}


def test_same_title_on_other_board_within_7_days_is_one_group() -> None:
    marked = mark_crossposts(
        [
            _post("academic", "2026학년도 2학기 수강신청 안내", "2026-08-01", "academic_notice"),
            _post("dept", "2026학년도  2학기 수강신청 안내", "2026-08-08", "dept_notice"),
            # 같은 제목이라도 8일 넘게 떨어진 회차는 교차 게시가 아니다.
            _post("next-year", "2026학년도 2학기 수강신청 안내", "2026-08-16", "dept_notice"),
        ]
    )

    assert _groups(marked) == {"academic": "xp-00001", "dept": "xp-00001", "next-year": None}


def test_same_board_repost_is_not_a_crosspost() -> None:
    marked = mark_crossposts(
        [
            _post("first", "대학 캠퍼스 방송 촬영 안내", "2026-07-23", "general_notice"),
            _post("second", "대학 캠퍼스 방송 촬영 안내", "2026-07-24", "general_notice"),
        ]
    )

    assert _groups(marked) == {"first": None, "second": None}


def test_chain_across_boards_closes_transitively_and_numbers_by_earliest_date() -> None:
    marked = mark_crossposts(
        [
            _post("late-a", "유고결석 신청 관련 공지", "2026-03-31", "board_a"),
            _post("late-b", "유고결석 신청 관련 공지", "2026-04-03", "board_b"),
            _post("late-c", "유고결석 신청 관련 공지", "2026-04-09", "board_c"),
            _post("early-a", "유고결석 신청 관련 공지", "2025-04-01", "board_a"),
            _post("early-b", "유고결석 신청 관련 공지", "2025-04-01", "board_b"),
            _post("no-date", "유고결석 신청 관련 공지", None, "board_c"),
            _post("no-board", "유고결석 신청 관련 공지", "2025-04-01", None),
        ]
    )

    assert _groups(marked) == {
        "late-a": "xp-00002",
        "late-b": "xp-00002",
        "late-c": "xp-00002",  # late-a와는 9일 차이지만 late-b를 거쳐 이어진다.
        "early-a": "xp-00001",
        "early-b": "xp-00001",
        "no-date": None,
        "no-board": None,
    }
    assert summarize(marked) == {
        "posts": 7,
        "groups": 2,
        "posts_in_groups": 5,
        "group_size_counts": {2: 1, 3: 1},
    }


def test_main_writes_marked_copy_and_never_overwrites_raw(tmp_path) -> None:
    raw = tmp_path / "kau_notices_raw.json"
    posts = [
        _post("a", "같은 공지", "2026-08-01", "board_a"),
        _post("b", "같은 공지", "2026-08-02", "board_b"),
    ]
    raw.write_text(json.dumps(posts, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(SystemExit):
        main(["--input", str(raw), "--output", str(raw)])

    out = tmp_path / "kau_notices_marked.json"
    main(["--input", str(raw), "--output", str(out)])

    assert json.loads(raw.read_text(encoding="utf-8")) == posts
    assert [post["crosspost_group_id"] for post in json.loads(out.read_text(encoding="utf-8"))] == [
        "xp-00001",
        "xp-00001",
    ]
