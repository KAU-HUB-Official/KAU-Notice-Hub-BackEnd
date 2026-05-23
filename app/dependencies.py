import fcntl
import logging
import sqlite3
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from app.config import get_settings
from app.db import SCHEMA_VERSION, connect, read_schema_version
from app.ingest import ingest_json_snapshot
from app.repository import JsonNoticeRepository, NoticeRepository
from app.service import NoticeService
from app.sqlite_repository import SqliteNoticeRepository

logger = logging.getLogger("app.dependencies")


@lru_cache
def get_notice_service() -> NoticeService:
    return NoticeService(_build_repository())


def _build_repository() -> NoticeRepository:
    settings = get_settings()
    db_path = settings.notice_db_path.expanduser().resolve()
    json_path = settings.notice_json_path.expanduser().resolve()

    if db_path.exists() and _db_schema_matches(db_path):
        return SqliteNoticeRepository(db_path)

    if not json_path.exists():
        if db_path.exists():
            logger.warning(
                "notice DB schema is outdated (expected v%s) and no JSON snapshot is available "
                "to re-ingest; continuing with the existing DB which may misbehave",
                SCHEMA_VERSION,
            )
            return SqliteNoticeRepository(db_path)
        logger.warning(
            "neither notice DB nor JSON snapshot exists; using JSON repository fallback"
        )
        return JsonNoticeRepository(json_path)

    lock_path = db_path.with_suffix(db_path.suffix + ".lock")
    with _exclusive_lock(lock_path):
        if not (db_path.exists() and _db_schema_matches(db_path)):
            try:
                if db_path.exists():
                    db_path.unlink()
                ingest_json_snapshot(json_path=json_path, db_path=db_path)
            except Exception:
                logger.exception(
                    "bootstrap ingest failed; falling back to JSON repository"
                )
                return JsonNoticeRepository(json_path)
    return SqliteNoticeRepository(db_path)


def _db_schema_matches(db_path: Path) -> bool:
    try:
        conn = connect(db_path)
    except sqlite3.Error:
        return False
    try:
        return read_schema_version(conn) == SCHEMA_VERSION
    finally:
        conn.close()


@contextmanager
def _exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    file = path.open("w", encoding="utf-8")
    try:
        fcntl.flock(file.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(file.fileno(), fcntl.LOCK_UN)
        finally:
            file.close()
