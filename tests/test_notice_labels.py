import asyncio
import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_notice_service
from app.ingest import ingest_json_snapshot
from app.main import app
from app.notice_labels import TARGETS, covers, label_url_key, load_notice_labels
from app.repository import NoticeSearchQuery
from app.service import NoticeService
from app.sqlite_repository import SqliteNoticeRepository


def _notice(notice_id: str, url: str, date: str = "2026-04-20") -> dict:
    return {
        "id": notice_id,
        "title": f"{notice_id} 공지",
        "content": "본문",
        "published_at": date,
        "original_url": url,
    }


def _label(url: str, audiences: list[str], excludes: list[str] | None = None) -> dict:
    return {
        "url": url,
        "prod_id": "ignored",
        "audiences": audiences,
        "excludes": excludes or [],
        "series": "수강신청 일정 안내",
        "term": "2026-1",
        "departments": [],
        "label_version": "v5-2026-10-15",
        "label_source": "r1",
    }


def _ingest(tmp_path: Path, notices: list[dict], label_lines: list[str] | None) -> Path:
    json_path = tmp_path / "notices.json"
    db_path = tmp_path / "notices.db"
    labels_path = tmp_path / "notice_labels.jsonl"
    json_path.write_text(json.dumps(notices, ensure_ascii=False), encoding="utf-8")
    if label_lines is not None:
        labels_path.write_text("\n".join(label_lines) + "\n", encoding="utf-8")
    ingest_json_snapshot(json_path=json_path, db_path=db_path, labels_path=labels_path)
    return db_path


def _lines(*labels: dict) -> list[str]:
    return [json.dumps(label, ensure_ascii=False) for label in labels]


def _ids(db_path: Path, target: str | None) -> set[str]:
    result = asyncio.run(
        SqliteNoticeRepository(db_path).search(
            NoticeSearchQuery(target=target, page_size=100)
        )
    )
    return {notice.id for notice in result.items}


# --- 대상 판정 규칙 (noticebench/audience.py covers와 같은 결과) ---


@pytest.mark.parametrize("target", TARGETS)
def test_empty_audiences_cover_every_target(target: str) -> None:
    assert covers([], target)


def test_undergraduate_notice_covers_freshmen() -> None:
    assert covers(["학부재학생"], "신입생·편입생")


def test_freshmen_exclusion_hides_undergraduate_notice_from_freshmen() -> None:
    assert not covers(["학부재학생"], "신입생·편입생", ["신입생·편입생"])
    assert covers(["학부재학생"], "학부재학생", ["신입생·편입생"])


def test_policy_graduate_school_is_special_graduate_school() -> None:
    assert covers(["항공우주정책대학원생"], "특수대학원생")


def test_graduate_notice_does_not_cover_undergraduate() -> None:
    assert not covers(["일반대학원생"], "학부재학생")


# --- URL 키 ---


@pytest.mark.parametrize(
    "variant",
    [
        "https://kau.ac.kr/kaulife/acdnoti.php?code=s1201&mode=read&seq=8058",
        "http://kau.ac.kr/kaulife/acdnoti.php?code=s1201&mode=read&seq=8058",
        "https://www.kau.ac.kr/kaulife/acdnoti.php?code=s1201&mode=read&seq=8058",
        "https://WWW.KAU.AC.KR/kaulife/acdnoti.php?seq=8058&mode=read&code=s1201",
    ],
)
def test_label_url_key_ignores_scheme_www_case_and_query_order(variant: str) -> None:
    assert label_url_key(variant) == "kau.ac.kr/kaulife/acdnoti.php?code=s1201&mode=read&seq=8058"


def test_label_url_key_keeps_distinct_notices_apart() -> None:
    assert label_url_key("https://kau.ac.kr/a.php?seq=1") != label_url_key(
        "https://kau.ac.kr/a.php?seq=2"
    )
    assert label_url_key(None) is None
    assert label_url_key("  ") is None


# --- ingest ---


def test_label_attaches_across_url_variants(tmp_path: Path) -> None:
    db_path = _ingest(
        tmp_path,
        [_notice("n-1", "https://www.kau.ac.kr/kaulife/acdnoti.php?seq=8058&mode=read&code=s1201")],
        _lines(
            _label(
                "http://kau.ac.kr/kaulife/acdnoti.php?code=s1201&mode=read&seq=8058",
                ["학부재학생"],
                ["신입생·편입생"],
            )
        ),
    )

    notice = asyncio.run(SqliteNoticeRepository(db_path).get_by_id("n-1"))
    assert notice is not None
    assert notice.targetAudiences == ["학부재학생"]
    assert notice.targetExcludes == ["신입생·편입생"]


def test_ingest_succeeds_without_labels_file(tmp_path: Path, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="app.notice_labels"):
        db_path = _ingest(tmp_path, [_notice("n-1", "https://kau.ac.kr/a.php?seq=1")], None)

    notice = asyncio.run(SqliteNoticeRepository(db_path).get_by_id("n-1"))
    assert notice is not None
    assert notice.targetAudiences is None
    assert notice.targetExcludes == []
    assert "notice labels file not found" in caplog.text


def test_ingest_skips_broken_label_lines(tmp_path: Path, caplog) -> None:
    lines = [
        "{not json",
        json.dumps({"url": "https://kau.ac.kr/a.php?seq=2", "audiences": "학부재학생"}),
        json.dumps(["not", "an", "object"]),
        *_lines(_label("https://kau.ac.kr/a.php?seq=1", ["교직원"])),
    ]
    with caplog.at_level(logging.INFO):
        db_path = _ingest(
            tmp_path,
            [
                _notice("n-1", "https://kau.ac.kr/a.php?seq=1"),
                _notice("n-2", "https://kau.ac.kr/a.php?seq=2"),
            ],
            lines,
        )

    repository = SqliteNoticeRepository(db_path)
    assert asyncio.run(repository.get_by_id("n-1")).targetAudiences == ["교직원"]
    assert asyncio.run(repository.get_by_id("n-2")).targetAudiences is None
    assert "invalid_lines=3" in caplog.text
    assert "labeled=1 unlabeled=1" in caplog.text


def test_load_notice_labels_keeps_first_of_duplicated_urls(tmp_path: Path) -> None:
    path = tmp_path / "labels.jsonl"
    path.write_text(
        "\n".join(
            _lines(
                _label("https://kau.ac.kr/a.php?seq=1", ["교직원"]),
                _label("http://www.kau.ac.kr/a.php?seq=1", ["외부"]),
            )
        ),
        encoding="utf-8",
    )

    labels = load_notice_labels(path)
    assert [label.audiences for label in labels.values()] == [("교직원",)]


# --- 목록 target 필터 ---


@pytest.fixture()
def labeled_db(tmp_path: Path) -> Path:
    return _ingest(
        tmp_path,
        [
            _notice("all", "https://kau.ac.kr/a.php?seq=1"),
            _notice("undergrad", "https://kau.ac.kr/a.php?seq=2"),
            _notice("undergrad-no-freshmen", "https://kau.ac.kr/a.php?seq=3"),
            _notice("policy-grad", "https://kau.ac.kr/a.php?seq=4"),
            _notice("grad", "https://kau.ac.kr/a.php?seq=5"),
            _notice("unlabeled", "https://kau.ac.kr/a.php?seq=6"),
        ],
        _lines(
            _label("https://kau.ac.kr/a.php?seq=1", []),
            _label("https://kau.ac.kr/a.php?seq=2", ["학부재학생"]),
            _label("https://kau.ac.kr/a.php?seq=3", ["학부재학생"], ["신입생·편입생"]),
            _label("https://kau.ac.kr/a.php?seq=4", ["항공우주정책대학원생"]),
            _label("https://kau.ac.kr/a.php?seq=5", ["일반대학원생"]),
        ),
    )


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("학부재학생", {"all", "undergrad", "undergrad-no-freshmen", "unlabeled"}),
        ("신입생·편입생", {"all", "undergrad", "unlabeled"}),
        ("일반대학원생", {"all", "grad", "unlabeled"}),
        ("특수대학원생", {"all", "policy-grad", "unlabeled"}),
        ("교직원·기타", {"all", "unlabeled"}),
    ],
)
def test_target_filter_follows_covers_and_keeps_unlabeled(
    labeled_db: Path, target: str, expected: set[str]
) -> None:
    assert _ids(labeled_db, target) == expected


@pytest.mark.parametrize("target", [None, "", "전체", "모르는값"])
def test_missing_or_unknown_target_does_not_filter(labeled_db: Path, target) -> None:
    assert len(_ids(labeled_db, target)) == 6


def test_target_filter_combines_with_search_query(labeled_db: Path) -> None:
    result = asyncio.run(
        SqliteNoticeRepository(labeled_db).search(
            NoticeSearchQuery(q="grad 공지", target="학부재학생", page_size=100)
        )
    )
    assert "grad" not in {notice.id for notice in result.items}
    assert "policy-grad" not in {notice.id for notice in result.items}


def test_list_api_accepts_target_and_returns_label_fields(labeled_db: Path) -> None:
    app.dependency_overrides[get_notice_service] = lambda: NoticeService(
        SqliteNoticeRepository(labeled_db)
    )
    try:
        with TestClient(app) as client:
            res = client.get("/api/notices", params={"target": "특수대학원생", "pageSize": 100})
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 200
    items = {item["id"]: item for item in res.json()["items"]}
    assert set(items) == {"all", "policy-grad", "unlabeled"}
    assert items["all"]["targetAudiences"] == []
    assert items["policy-grad"]["targetAudiences"] == ["항공우주정책대학원생"]
    assert items["unlabeled"]["targetAudiences"] is None
    assert items["unlabeled"]["targetExcludes"] == []
