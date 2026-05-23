from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS notices (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        summary TEXT,
        url TEXT,
        category TEXT,
        department TEXT,
        published_at TEXT,
        audience_group TEXT,
        source_group TEXT,
        searchable_text TEXT,
        searchable_compact TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS notice_sources (
        notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
        source_name TEXT NOT NULL,
        source_order INTEGER NOT NULL,
        PRIMARY KEY (notice_id, source_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS notice_source_groups (
        notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
        source_group TEXT NOT NULL,
        source_group_order INTEGER NOT NULL,
        PRIMARY KEY (notice_id, source_group)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS notice_attachments (
        notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
        attachment_order INTEGER NOT NULL,
        name TEXT NOT NULL,
        url TEXT NOT NULL,
        PRIMARY KEY (notice_id, attachment_order)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS notice_tags (
        notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
        tag TEXT NOT NULL,
        tag_order INTEGER NOT NULL,
        PRIMARY KEY (notice_id, tag)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS schema_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_notices_published_at ON notices(published_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_notices_audience_group ON notices(audience_group)",
    "CREATE INDEX IF NOT EXISTS idx_notices_source_group ON notices(source_group)",
    "CREATE INDEX IF NOT EXISTS idx_notices_category ON notices(category)",
    "CREATE INDEX IF NOT EXISTS idx_notices_department ON notices(department)",
    "CREATE INDEX IF NOT EXISTS idx_notice_sources_source_name ON notice_sources(source_name)",
    "CREATE INDEX IF NOT EXISTS idx_notice_source_groups_source_group ON notice_source_groups(source_group)",
)


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_schema(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    conn.execute(
        "INSERT INTO schema_meta(key, value) VALUES('version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),),
    )


def read_schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'version'"
        ).fetchone()
    except sqlite3.Error:
        return 0
    if not row:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return 0
