import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from app.db import connect, initialize_schema
from app.ingest import ingest_json_snapshot
from app.repository import NoticeRepositoryError, NoticeSearchQuery
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


def test_sqlite_repository_normalizes_legacy_html_content_on_read(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    conn = connect(db_path)
    try:
        initialize_schema(conn)
        conn.execute(
            """
            INSERT INTO notices (
                id, title, content, url, category, department,
                published_at, audience_group, source_group,
                searchable_text, searchable_compact
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy",
                "레거시 HTML 공지",
                '<p><img src="data:image/png;base64,AAAA" alt="본문"></p>',
                None,
                None,
                None,
                None,
                None,
                None,
                "",
                "",
            ),
        )
    finally:
        conn.close()

    repository = SqliteNoticeRepository(db_path)
    notice = asyncio.run(repository.get_by_id("legacy"))

    assert notice is not None
    assert notice.content == "**[이미지 본문]**\n\n원문 공지에서 이미지를 확인해주세요."
    assert "data:image" not in notice.content


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


def test_ingest_populates_facet_cache(populated_db: Path) -> None:
    conn = connect(populated_db)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM notice_facets_cache"
        ).fetchone()[0]
    finally:
        conn.close()
    # At minimum the no-filter (audience='', source_group='') bundle exists.
    assert count >= 1


def test_facet_cache_matches_live_computation(populated_db: Path) -> None:
    repository = SqliteNoticeRepository(populated_db)

    conn = connect(populated_db)
    try:
        audiences = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT audience_group FROM notices "
                "WHERE audience_group IS NOT NULL"
            ).fetchall()
            if row[0]
        ]
    finally:
        conn.close()

    queries = [NoticeSearchQuery()]
    queries += [NoticeSearchQuery(audience_group=a) for a in audiences]

    cached = [asyncio.run(repository.search(q)) for q in queries]

    # Wipe the cache so the repository falls back to live computation.
    conn = connect(populated_db)
    try:
        conn.execute("DELETE FROM notice_facets_cache")
    finally:
        conn.close()

    for query, cached_result in zip(queries, cached):
        live_result = asyncio.run(repository.search(query))
        assert cached_result.facets == live_result.facets
        assert (
            cached_result.effective_source_group
            == live_result.effective_source_group
        )


def test_ingest_precomputes_content_markdown(tmp_path: Path) -> None:
    json_path = tmp_path / "notices.json"
    db_path = tmp_path / "notices.db"
    _write_json(
        json_path,
        [
            {
                "id": "html-1",
                "title": "HTML 공지",
                "content": "<p>본문 <b>강조</b></p>",
                "published_at": "2026-04-20",
            }
        ],
    )
    ingest_json_snapshot(json_path=json_path, db_path=db_path)

    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT content, content_markdown FROM notices WHERE id = ?",
            ("html-1",),
        ).fetchone()
    finally:
        conn.close()

    # The column is populated and already holds render-ready markdown.
    assert row["content_markdown"] is not None
    assert row["content_markdown"] == row["content"]
    assert "<p>" not in row["content_markdown"]

    # The read path returns the precomputed value verbatim.
    repository = SqliteNoticeRepository(db_path)
    notice = asyncio.run(repository.get_by_id("html-1"))
    assert notice is not None
    assert notice.content == row["content_markdown"]


def test_new_code_reads_legacy_v2_db_without_crashing(tmp_path: Path) -> None:
    # A pre-v3 DB has no content_markdown column and no notice_facets_cache.
    # New code must self-heal (ALTER + cache table) instead of crashing.
    db_path = tmp_path / "legacy_v2.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE notices(
                id TEXT PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL,
                summary TEXT, url TEXT, category TEXT, department TEXT,
                published_at TEXT, audience_group TEXT, source_group TEXT,
                searchable_text TEXT, searchable_compact TEXT);
            CREATE TABLE notice_sources(notice_id TEXT, source_name TEXT,
                source_order INTEGER, PRIMARY KEY(notice_id, source_name));
            CREATE TABLE notice_source_groups(notice_id TEXT, source_group TEXT,
                source_group_order INTEGER, PRIMARY KEY(notice_id, source_group));
            CREATE TABLE notice_attachments(notice_id TEXT, attachment_order INTEGER,
                name TEXT, url TEXT, PRIMARY KEY(notice_id, attachment_order));
            CREATE TABLE notice_tags(notice_id TEXT, tag TEXT, tag_order INTEGER,
                PRIMARY KEY(notice_id, tag));
            CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO schema_meta VALUES('version', '2');
            INSERT INTO notices(id, title, content, searchable_text, searchable_compact)
                VALUES('x', '레거시 공지', '<p>HTML 본문</p>', 'html 본문', 'html본문');
            """
        )
        conn.commit()
    finally:
        conn.close()

    repository = SqliteNoticeRepository(db_path)

    result = asyncio.run(repository.search(NoticeSearchQuery()))
    assert len(result.items) == 1
    # Legacy NULL content_markdown -> normalized on read (no raw HTML leaks).
    assert "<p>" not in result.items[0].content

    notice = asyncio.run(repository.get_by_id("x"))
    assert notice is not None
    assert "<p>" not in notice.content


def test_unknown_audience_falls_back_to_live_facets(populated_db: Path) -> None:
    from app import sqlite_repository as repo_module

    repository = SqliteNoticeRepository(populated_db)
    unknown = "존재하지않는대상그룹"

    # The cache has no row for an audience that was never ingested.
    conn = connect(populated_db)
    try:
        assert repo_module._read_facet_row(conn, unknown, None) is None
        live_facets, live_effective = repo_module._compute_facets_live(
            conn,
            audience=unknown,
            requested_source_group=None,
            source_filter_enabled=False,
        )
    finally:
        conn.close()

    result = asyncio.run(
        repository.search(NoticeSearchQuery(audience_group=unknown))
    )
    # Falls back to live computation and stays consistent (no crash).
    assert result.facets == live_facets
    assert result.effective_source_group == live_effective


def test_schema_creates_expected_tables(populated_db: Path) -> None:
    with sqlite3.connect(populated_db) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    names = {row[0] for row in rows}
    assert {"notices", "notice_sources", "notice_attachments", "notice_tags"}.issubset(names)
