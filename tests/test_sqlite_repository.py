import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from app.ingest import ingest_json_snapshot
from app.repository import NoticeRepositoryError
from app.sqlite_repository import SqliteNoticeRepository


def _write_json(path: Path, data: list[dict]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def populated_db(tmp_path):
    json_path = tmp_path / "notices.json"
    db_path = tmp_path / "notices.db"
    _write_json(
        json_path,
        [
            {
                "id": "n-1",
                "title": "수강신청 안내",
                "content": "수강신청 본문",
                "source_name": [
                    "한국항공대학교 공식 홈페이지",
                    "교무처 홈페이지",
                ],
                "category_raw": "학사",
                "department": "교무처",
                "published_at": "2026-04-20",
                "original_url": "https://example.com/1",
                "attachments": [
                    {"name": "수강편람.pdf", "url": "https://example.com/1.pdf"}
                ],
            },
            {
                "id": "n-2",
                "title": "장학금 신청",
                "content": "장학금 본문",
                "source_name": "한국항공대학교 학생지원처",
                "category_raw": "장학",
                "department": "학생지원처",
                "published_at": "2026-04-21",
                "original_url": "https://example.com/2",
            },
        ],
    )
    ingest_json_snapshot(json_path=json_path, db_path=db_path)
    return db_path


def test_sqlite_repository_list_all_returns_notices_with_sources(populated_db: Path) -> None:
    repository = SqliteNoticeRepository(populated_db)
    notices = asyncio.run(repository.list_all())

    assert [n.id for n in notices] == ["n-2", "n-1"]
    first = notices[1]
    assert first.title == "수강신청 안내"
    assert first.source == "한국항공대학교 공식 홈페이지"
    assert first.sources == [
        "한국항공대학교 공식 홈페이지",
        "교무처 홈페이지",
    ]
    assert first.attachments[0].url == "https://example.com/1.pdf"
    assert "학사" in first.tags


def test_sqlite_repository_get_by_id(populated_db: Path) -> None:
    repository = SqliteNoticeRepository(populated_db)
    notice = asyncio.run(repository.get_by_id("n-2"))
    assert notice is not None
    assert notice.category == "장학"
    assert notice.source == "한국항공대학교 학생지원처"


def test_sqlite_repository_get_by_id_missing(populated_db: Path) -> None:
    repository = SqliteNoticeRepository(populated_db)
    notice = asyncio.run(repository.get_by_id("no-such-id"))
    assert notice is None


def test_ingest_replaces_existing_db_atomically(tmp_path) -> None:
    json_path = tmp_path / "notices.json"
    db_path = tmp_path / "notices.db"

    _write_json(
        json_path,
        [{"id": "n-1", "title": "첫 공지", "content": "본문"}],
    )
    ingest_json_snapshot(json_path=json_path, db_path=db_path)

    _write_json(
        json_path,
        [{"id": "n-2", "title": "둘째 공지", "content": "본문"}],
    )
    ingest_json_snapshot(json_path=json_path, db_path=db_path)

    repository = SqliteNoticeRepository(db_path)
    notices = asyncio.run(repository.list_all())
    assert [n.id for n in notices] == ["n-2"]


def test_ingest_normalizes_duplicate_ids(tmp_path) -> None:
    json_path = tmp_path / "notices.json"
    db_path = tmp_path / "notices.db"
    _write_json(
        json_path,
        [
            {"id": "same", "title": "첫 공지", "content": "본문"},
            {"id": "same", "title": "둘째 공지", "content": "본문"},
        ],
    )

    ingest_json_snapshot(json_path=json_path, db_path=db_path)

    repository = SqliteNoticeRepository(db_path)
    notices = asyncio.run(repository.list_all())
    ids = sorted(n.id for n in notices)
    assert ids == ["same", "same-2"]


def test_ingest_rejects_non_array_json(tmp_path) -> None:
    json_path = tmp_path / "notices.json"
    db_path = tmp_path / "notices.db"
    json_path.write_text('{"not": "array"}', encoding="utf-8")

    with pytest.raises(ValueError):
        ingest_json_snapshot(json_path=json_path, db_path=db_path)
    assert not db_path.exists()


def test_sqlite_repository_wraps_db_errors(tmp_path) -> None:
    db_path = tmp_path / "broken.db"
    db_path.write_bytes(b"not a sqlite database")

    repository = SqliteNoticeRepository(db_path)
    with pytest.raises(NoticeRepositoryError):
        asyncio.run(repository.list_all())


def test_ingest_persists_attachment_order(tmp_path) -> None:
    json_path = tmp_path / "notices.json"
    db_path = tmp_path / "notices.db"
    _write_json(
        json_path,
        [
            {
                "id": "n-1",
                "title": "첨부 다수",
                "content": "본문",
                "attachments": [
                    {"name": "a.pdf", "url": "https://example.com/a.pdf"},
                    {"name": "b.pdf", "url": "https://example.com/b.pdf"},
                    {"name": "c.pdf", "url": "https://example.com/c.pdf"},
                ],
            }
        ],
    )
    ingest_json_snapshot(json_path=json_path, db_path=db_path)

    repository = SqliteNoticeRepository(db_path)
    notice = asyncio.run(repository.get_by_id("n-1"))
    assert notice is not None
    assert [a.name for a in notice.attachments] == ["a.pdf", "b.pdf", "c.pdf"]


def test_schema_creates_expected_tables(populated_db: Path) -> None:
    with sqlite3.connect(populated_db) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    names = {row[0] for row in rows}
    assert {"notices", "notice_sources", "notice_attachments", "notice_tags"}.issubset(names)
