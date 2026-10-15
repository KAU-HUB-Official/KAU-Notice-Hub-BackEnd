import asyncio
import json
import logging
import os
import time
from pathlib import Path

import pytest

from app.config import Settings
from app import crawler_scheduler
from app.crawler_scheduler import (
    FileLock,
    publish_crawler_snapshot,
    run_crawler_scheduler,
    _scheduler_lock_path,
)


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_publish_crawler_snapshot_replaces_file_after_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_path = tmp_path / "notices.json"
    write_json(final_path, [{"id": "old"}])

    def fake_crawl_all_notices(*, max_pages: int, output_path: Path):
        assert max_pages == 7
        write_json(output_path, [{"id": "new"}, {"id": "new-2"}])
        return [{"id": "new"}, {"id": "new-2"}], []

    monkeypatch.setattr(crawler_scheduler, "_crawl_all_notices", fake_crawl_all_notices)

    result = publish_crawler_snapshot(
        Settings(
            notice_json_path=final_path,
            notice_db_path=tmp_path / "notices.db",
            crawler_max_pages=7,
            crawler_min_records=1,
            crawler_min_retain_ratio=0.5,
        )
    )

    assert result is not None
    assert result.output_path == final_path.resolve()
    assert result.total_records == 2
    assert json.loads(final_path.read_text(encoding="utf-8")) == [
        {"id": "new"},
        {"id": "new-2"},
    ]


def test_publish_crawler_snapshot_keeps_file_on_large_record_drop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_path = tmp_path / "notices.json"
    write_json(final_path, [{"id": str(index)} for index in range(10)])

    def fake_crawl_all_notices(*, max_pages: int, output_path: Path):
        write_json(output_path, [{"id": "only-one"}])
        return [{"id": "only-one"}], []

    monkeypatch.setattr(crawler_scheduler, "_crawl_all_notices", fake_crawl_all_notices)

    with pytest.raises(ValueError, match="record count dropped"):
        publish_crawler_snapshot(
            Settings(
                notice_json_path=final_path,
                notice_db_path=tmp_path / "notices.db",
                crawler_min_records=1,
                crawler_min_retain_ratio=0.5,
            )
        )

    assert len(json.loads(final_path.read_text(encoding="utf-8"))) == 10


def test_publish_crawler_snapshot_allows_drop_when_old_records_are_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_path = tmp_path / "notices.json"
    write_json(
        final_path,
        [
            {"id": str(index), "published_at": "2024-01-01"}
            for index in range(10)
        ],
    )

    def fake_crawl_all_notices(*, max_pages: int, output_path: Path):
        write_json(output_path, [{"id": "recent", "published_at": "2026-04-01"}])
        return [{"id": "recent", "published_at": "2026-04-01"}], []

    monkeypatch.setattr(crawler_scheduler, "_crawl_all_notices", fake_crawl_all_notices)

    result = publish_crawler_snapshot(
        Settings(
            notice_json_path=final_path,
            notice_db_path=tmp_path / "notices.db",
            crawler_min_records=1,
            crawler_min_retain_ratio=0.5,
        )
    )

    assert result is not None
    assert result.total_records == 1
    assert json.loads(final_path.read_text(encoding="utf-8")) == [
        {"id": "recent", "published_at": "2026-04-01"}
    ]



def _make_file(path: Path, *, size: int, age_seconds: float) -> None:
    path.write_bytes(b"x" * size)
    mtime = time.time() - age_seconds
    os.utime(path, (mtime, mtime))


def test_publish_crawler_snapshot_removes_stale_temp_snapshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    final_path = tmp_path / "kau_official_posts.json"
    write_json(final_path, [{"id": "old"}])
    hours = 60 * 60

    # Orphans left by killed publishes (scheduler 8-char and script 6-char suffixes).
    stale_scheduler = tmp_path / ".kau_official_posts.json.tmp.abcd1234"
    stale_script = tmp_path / ".kau_official_posts.json.tmp.Xy12Zw"
    _make_file(stale_scheduler, size=300, age_seconds=7 * hours)
    _make_file(stale_script, size=200, age_seconds=30 * 24 * hours)

    # Must survive: a recent temp file (possibly an in-flight manual crawl),
    # and old backups / unrelated files.
    recent_tmp = tmp_path / ".kau_official_posts.json.tmp.recent01"
    backup = tmp_path / "kau_official_posts.json.bak"
    timestamped_backup = tmp_path / "kau_official_posts.json.bak-20260501000000"
    db_tmp = tmp_path / ".notices.db.tmp.abcd1234"
    _make_file(recent_tmp, size=10, age_seconds=1 * hours)
    _make_file(backup, size=10, age_seconds=60 * 24 * hours)
    _make_file(timestamped_backup, size=10, age_seconds=60 * 24 * hours)
    _make_file(db_tmp, size=10, age_seconds=60 * 24 * hours)
    os.utime(final_path, (time.time() - 60 * 24 * hours,) * 2)

    seen_output_paths: list[Path] = []

    def fake_crawl_all_notices(*, max_pages: int, output_path: Path):
        seen_output_paths.append(output_path)
        assert output_path.exists()
        write_json(output_path, [{"id": "new"}])
        return [{"id": "new"}], []

    monkeypatch.setattr(crawler_scheduler, "_crawl_all_notices", fake_crawl_all_notices)

    with caplog.at_level(logging.INFO, logger="app.crawler_scheduler"):
        result = publish_crawler_snapshot(
            Settings(
                notice_json_path=final_path,
                notice_db_path=tmp_path / "notices.db",
                crawler_min_records=1,
                crawler_min_retain_ratio=0.5,
            )
        )

    assert result is not None
    assert not stale_scheduler.exists()
    assert not stale_script.exists()
    assert recent_tmp.exists()
    assert backup.exists()
    assert timestamped_backup.exists()
    assert db_tmp.exists()
    assert json.loads(final_path.read_text(encoding="utf-8")) == [{"id": "new"}]
    # This publish's own temp file was used, then consumed by os.replace.
    assert len(seen_output_paths) == 1
    assert not seen_output_paths[0].exists()

    messages = [r.getMessage() for r in caplog.records]
    assert any(
        "removed stale temp snapshots" in m and "count=2" in m and "bytes=500" in m
        for m in messages
    )


def test_publish_crawler_snapshot_skips_temp_cleanup_without_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_path = tmp_path / "kau_official_posts.json"
    write_json(final_path, [{"id": "old"}])
    stale_tmp = tmp_path / ".kau_official_posts.json.tmp.abcd1234"
    _make_file(stale_tmp, size=10, age_seconds=7 * 60 * 60)

    def fail_crawl(**_kwargs):
        raise AssertionError("crawl must not run while another crawler holds the lock")

    monkeypatch.setattr(crawler_scheduler, "_crawl_all_notices", fail_crawl)

    with FileLock(tmp_path / ".crawler.lock") as held:
        assert held
        result = publish_crawler_snapshot(
            Settings(
                notice_json_path=final_path,
                notice_db_path=tmp_path / "notices.db",
            )
        )

    assert result is None
    assert stale_tmp.exists()

def test_run_crawler_scheduler_is_singleton_across_workers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulate a second worker: the scheduler lock is already held elsewhere.
    settings = Settings(
        notice_json_path=tmp_path / "notices.json",
        notice_db_path=tmp_path / "notices.db",
        crawler_run_on_startup=True,
    )

    calls = 0

    async def fake_run_once(_settings) -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(crawler_scheduler, "_run_once", fake_run_once)

    with FileLock(_scheduler_lock_path(settings)) as held:
        assert held  # first "worker" owns the lock
        # second worker must skip immediately (no startup crawl, no loop)
        asyncio.run(asyncio.wait_for(run_crawler_scheduler(settings), timeout=2))

    assert calls == 0
