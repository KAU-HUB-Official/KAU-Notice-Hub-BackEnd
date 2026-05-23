import asyncio
import json
from pathlib import Path

import pytest

from app.config import Settings, get_settings
from app.dependencies import _build_repository, get_notice_service
from app.repository import JsonNoticeRepository
from app.sqlite_repository import SqliteNoticeRepository


def _write_snapshot(path: Path) -> None:
    path.write_text(
        json.dumps(
            [{"id": "boot-1", "title": "부트스트랩 공지", "content": "본문"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _clear_caches():
    get_settings.cache_clear()
    get_notice_service.cache_clear()
    yield
    get_settings.cache_clear()
    get_notice_service.cache_clear()


def _override_settings(monkeypatch, json_path: Path, db_path: Path) -> None:
    def _fake_get_settings() -> Settings:
        return Settings(notice_json_path=json_path, notice_db_path=db_path)

    monkeypatch.setattr("app.dependencies.get_settings", _fake_get_settings)


def test_bootstrap_ingests_from_json_when_db_missing(monkeypatch, tmp_path) -> None:
    json_path = tmp_path / "snapshot.json"
    db_path = tmp_path / "notice.db"
    _write_snapshot(json_path)
    _override_settings(monkeypatch, json_path, db_path)

    repository = _build_repository()
    assert isinstance(repository, SqliteNoticeRepository)
    assert db_path.exists()

    notices = asyncio.run(repository.list_all())
    assert [n.id for n in notices] == ["boot-1"]


def test_bootstrap_falls_back_to_json_when_snapshot_missing(monkeypatch, tmp_path) -> None:
    json_path = tmp_path / "missing.json"
    db_path = tmp_path / "missing.db"
    _override_settings(monkeypatch, json_path, db_path)

    repository = _build_repository()
    assert isinstance(repository, JsonNoticeRepository)


def test_existing_db_is_reused(monkeypatch, tmp_path) -> None:
    json_path = tmp_path / "snapshot.json"
    db_path = tmp_path / "notice.db"
    _write_snapshot(json_path)
    _override_settings(monkeypatch, json_path, db_path)

    first = _build_repository()
    assert isinstance(first, SqliteNoticeRepository)
    mtime_before = db_path.stat().st_mtime_ns

    json_path.write_text(
        json.dumps([{"id": "boot-2", "title": "다른 공지", "content": "본문"}]),
        encoding="utf-8",
    )
    second = _build_repository()
    assert isinstance(second, SqliteNoticeRepository)
    assert db_path.stat().st_mtime_ns == mtime_before

    notices = asyncio.run(second.list_all())
    assert [n.id for n in notices] == ["boot-1"]


def test_concurrent_bootstrap_runs_ingest_once(monkeypatch, tmp_path) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from app import dependencies

    json_path = tmp_path / "snapshot.json"
    db_path = tmp_path / "notice.db"
    _write_snapshot(json_path)
    _override_settings(monkeypatch, json_path, db_path)

    call_count = 0
    original_ingest = dependencies.ingest_json_snapshot

    def counting_ingest(**kwargs):
        nonlocal call_count
        call_count += 1
        return original_ingest(**kwargs)

    monkeypatch.setattr(dependencies, "ingest_json_snapshot", counting_ingest)

    start_barrier = threading.Barrier(4)

    def worker():
        start_barrier.wait()
        return dependencies._build_repository()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = [f.result() for f in [pool.submit(worker) for _ in range(4)]]

    assert all(isinstance(r, SqliteNoticeRepository) for r in results)
    assert call_count == 1, f"expected single ingest, got {call_count}"
