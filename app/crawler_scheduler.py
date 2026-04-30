from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from app.config import Settings

logger = logging.getLogger("app.crawler_scheduler")


@dataclass(frozen=True)
class CrawlerPublishResult:
    output_path: Path
    total_records: int


class FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._file = None

    def __enter__(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w", encoding="utf-8")
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._file.close()
            self._file = None
            return False
        self._file.write(str(os.getpid()))
        self._file.flush()
        return True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._file is None:
            return
        with contextlib.suppress(OSError):
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        self._file.close()
        self._file = None


def publish_crawler_snapshot(settings: Settings) -> CrawlerPublishResult | None:
    final_path = settings.notice_json_path.expanduser().resolve()
    final_path.parent.mkdir(parents=True, exist_ok=True)

    lock_path = (
        settings.crawler_lock_path.expanduser().resolve()
        if settings.crawler_lock_path
        else final_path.parent / ".crawler.lock"
    )

    with FileLock(lock_path) as acquired:
        if not acquired:
            logger.info("crawler publish skipped because another crawler is running")
            return None

        tmp_path = _prepare_temp_snapshot(final_path)
        try:
            _crawl_all_notices(
                max_pages=settings.crawler_max_pages,
                output_path=tmp_path,
            )
            total_records = _validate_snapshot(
                next_path=tmp_path,
                final_path=final_path,
                min_records=settings.crawler_min_records,
                min_retain_ratio=settings.crawler_min_retain_ratio,
            )
            os.replace(tmp_path, final_path)
            logger.info(
                "crawler publish completed: path=%s total_records=%s",
                final_path,
                total_records,
            )
            return CrawlerPublishResult(
                output_path=final_path,
                total_records=total_records,
            )
        finally:
            with contextlib.suppress(FileNotFoundError):
                tmp_path.unlink()


async def run_crawler_scheduler(settings: Settings) -> None:
    interval_seconds = max(1, settings.crawler_interval_seconds)
    logger.info(
        "crawler scheduler started: interval_seconds=%s run_on_startup=%s output=%s",
        interval_seconds,
        settings.crawler_run_on_startup,
        settings.notice_json_path,
    )

    if settings.crawler_run_on_startup:
        await _run_once(settings)

    while True:
        await asyncio.sleep(interval_seconds)
        await _run_once(settings)


async def _run_once(settings: Settings) -> None:
    try:
        await asyncio.to_thread(publish_crawler_snapshot, settings)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("crawler publish failed; keeping previous notice JSON")


def _prepare_temp_snapshot(final_path: Path) -> Path:
    tmp_file = tempfile.NamedTemporaryFile(
        delete=False,
        dir=final_path.parent,
        prefix=f".{final_path.name}.tmp.",
    )
    tmp_path = Path(tmp_file.name)
    tmp_file.close()

    if final_path.exists():
        shutil.copyfile(final_path, tmp_path)
    else:
        tmp_path.write_text("[]\n", encoding="utf-8")

    return tmp_path


def _crawl_all_notices(*, max_pages: int, output_path: Path):
    from app.crawler.main import crawl_all_notices

    return crawl_all_notices(max_pages=max_pages, output_path=output_path)


def _validate_snapshot(
    *,
    next_path: Path,
    final_path: Path,
    min_records: int,
    min_retain_ratio: float,
) -> int:
    try:
        next_data = json.loads(next_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Invalid crawler output JSON: {exc}") from exc

    if not isinstance(next_data, list):
        raise ValueError("Invalid crawler output JSON: root must be an array.")

    next_count = len(next_data)
    if next_count < min_records:
        raise ValueError(
            f"Refusing publish: record count {next_count} < "
            f"CRAWLER_MIN_RECORDS {min_records}."
        )

    old_count = 0
    if final_path.exists():
        try:
            old_data = json.loads(final_path.read_text(encoding="utf-8"))
            if isinstance(old_data, list):
                old_count = _count_retain_baseline_records(old_data)
        except Exception:
            old_count = 0

    if old_count > 0 and next_count < old_count * min_retain_ratio:
        raise ValueError(
            "Refusing publish: record count dropped from retain baseline "
            f"{old_count} to {next_count}, below "
            f"CRAWLER_MIN_RETAIN_RATIO {min_retain_ratio}."
        )

    return next_count


def _count_retain_baseline_records(data: list) -> int:
    from app.crawler.services.dedup_service import prune_stale_posts

    dict_items = [item for item in data if isinstance(item, dict)]
    return len(prune_stale_posts(dict_items).posts)
