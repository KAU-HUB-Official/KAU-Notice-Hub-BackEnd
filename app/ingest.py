from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.classification import (
    classify_notice_audience,
    classify_notice_source_group,
    classify_notice_source_groups,
    normalize_facet_value,
)
from app.db import connect, initialize_schema
from app.normalize import normalize_notice
from app.schemas import Notice
from app.search import build_search_text, compact_search_text
from app.sqlite_repository import build_and_store_facets

logger = logging.getLogger("app.ingest")


@dataclass(frozen=True)
class IngestResult:
    db_path: Path
    total_notices: int


@dataclass(frozen=True)
class _ClassifiedNotice:
    notice: Notice
    audience_group: str
    source_groups: list[str]
    representative_source_group: str | None
    searchable_text: str
    searchable_compact: str


def ingest_json_snapshot(
    *,
    json_path: str | Path,
    db_path: str | Path,
) -> IngestResult:
    json_file = Path(json_path).expanduser().resolve()
    final_db = Path(db_path).expanduser().resolve()
    final_db.parent.mkdir(parents=True, exist_ok=True)

    notices = _load_classified_notices(json_file)

    tmp_db_fd, tmp_db_name = tempfile.mkstemp(
        prefix=f".{final_db.name}.tmp.",
        dir=final_db.parent,
    )
    os.close(tmp_db_fd)
    tmp_db = Path(tmp_db_name)
    tmp_db.unlink()

    try:
        conn = connect(tmp_db)
        try:
            initialize_schema(conn)
            _write_notices(conn, notices)
            build_and_store_facets(conn)
        finally:
            conn.close()
        os.replace(tmp_db, final_db)
        logger.info(
            "ingest completed: db=%s notices=%s", final_db, len(notices)
        )
        return IngestResult(db_path=final_db, total_notices=len(notices))
    except Exception:
        with _suppress_missing():
            tmp_db.unlink()
        raise


def _load_classified_notices(json_path: Path) -> list[_ClassifiedNotice]:
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("공지 JSON 파일은 배열(Array) 형식이어야 합니다.")

    used_ids: dict[str, int] = {}
    classified: list[_ClassifiedNotice] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        notice = normalize_notice(item, index)
        current = used_ids.get(notice.id, 0)
        used_ids[notice.id] = current + 1
        if current > 0:
            notice = notice.model_copy(update={"id": f"{notice.id}-{current + 1}"})

        audience_group = classify_notice_audience(notice)
        source_groups = classify_notice_source_groups(notice)
        representative = classify_notice_source_group(notice)
        searchable_text = build_search_text(notice)
        searchable_compact = compact_search_text(searchable_text)

        classified.append(
            _ClassifiedNotice(
                notice=notice,
                audience_group=audience_group,
                source_groups=source_groups,
                representative_source_group=representative,
                searchable_text=searchable_text,
                searchable_compact=searchable_compact,
            )
        )
    return classified


def _write_notices(conn: sqlite3.Connection, items: list[_ClassifiedNotice]) -> None:
    conn.execute("BEGIN")
    try:
        conn.executemany(
            """
            INSERT INTO notices (
                id, title, content, url, category, department,
                published_at, audience_group, source_group,
                searchable_text, searchable_compact, content_markdown
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.notice.id,
                    item.notice.title,
                    item.notice.content,
                    item.notice.url,
                    normalize_facet_value(item.notice.category),
                    normalize_facet_value(item.notice.department),
                    item.notice.date,
                    item.audience_group,
                    item.representative_source_group,
                    item.searchable_text,
                    item.searchable_compact,
                    # normalize_notice() already produced render-ready markdown,
                    # so we persist it once here and skip re-normalizing per read.
                    item.notice.content,
                )
                for item in items
            ],
        )

        source_rows: list[tuple[str, str, int]] = []
        source_group_rows: list[tuple[str, str, int]] = []
        attachment_rows: list[tuple[str, int, str, str]] = []
        tag_rows: list[tuple[str, str, int]] = []

        for item in items:
            n = item.notice

            seen_sources: set[str] = set()
            order = 0
            for src in n.sources or ([n.source] if n.source else []):
                if not src or src in seen_sources:
                    continue
                seen_sources.add(src)
                source_rows.append((n.id, src, order))
                order += 1

            seen_groups: set[str] = set()
            group_order = 0
            for group in item.source_groups:
                if not group or group in seen_groups:
                    continue
                seen_groups.add(group)
                source_group_rows.append((n.id, group, group_order))
                group_order += 1

            for index, attachment in enumerate(n.attachments):
                attachment_rows.append(
                    (n.id, index, attachment.name, attachment.url)
                )

            seen_tags: set[str] = set()
            tag_order = 0
            for tag in n.tags:
                if not tag or tag in seen_tags:
                    continue
                seen_tags.add(tag)
                tag_rows.append((n.id, tag, tag_order))
                tag_order += 1

        if source_rows:
            conn.executemany(
                "INSERT INTO notice_sources (notice_id, source_name, source_order) "
                "VALUES (?, ?, ?)",
                source_rows,
            )
        if source_group_rows:
            conn.executemany(
                "INSERT INTO notice_source_groups (notice_id, source_group, source_group_order) "
                "VALUES (?, ?, ?)",
                source_group_rows,
            )
        if attachment_rows:
            conn.executemany(
                "INSERT INTO notice_attachments (notice_id, attachment_order, name, url) "
                "VALUES (?, ?, ?, ?)",
                attachment_rows,
            )
        if tag_rows:
            conn.executemany(
                "INSERT INTO notice_tags (notice_id, tag, tag_order) VALUES (?, ?, ?)",
                tag_rows,
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


class _suppress_missing:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        return exc_type is not None and issubclass(exc_type, FileNotFoundError)
