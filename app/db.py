from __future__ import annotations

import sqlite3
from pathlib import Path

# Bump on any schema change. Increments are one-way: on a version mismatch
# app/dependencies.py deletes the DB and re-ingests from JSON (no down-migration).
# v2 -> v3: added notices.content_markdown and the notice_facets_cache table.
SCHEMA_VERSION = 3

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
        searchable_compact TEXT,
        content_markdown TEXT
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
    CREATE TABLE IF NOT EXISTS notice_facets_cache (
        audience TEXT NOT NULL,
        source_group TEXT NOT NULL,
        payload TEXT NOT NULL,
        PRIMARY KEY (audience, source_group)
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
    # Read-oriented, per-connection tuning. We deliberately do NOT enable WAL
    # here: ingest publishes a new DB via os.replace() on the single .db file,
    # which is incompatible with WAL's -wal/-shm sidecar files. These pragmas
    # create no sidecar files and are safe with the atomic file swap.
    #
    # Connections are short-lived (one per request, see SqliteNoticeRepository),
    # so values are kept modest to stay well within the deployment memory budget
    # (Lightsail ~911MiB, MemoryMax 750M; see docs/DEPLOYMENT.md). mmap_size is
    # sized to cover the whole DB (~24MB today) with headroom; mmap pages are
    # shared read-only across connections via the OS page cache, so the resident
    # cost is bounded by the file size, not multiplied per connection.
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -8000")  # ~8MB page cache per connection
    conn.execute("PRAGMA mmap_size = 67108864")  # 64MB memory-mapped reads
    return conn


def _ensure_column(
    conn: sqlite3.Connection, table: str, column: str, decl: str
) -> None:
    """Add a column to an existing table if it is missing (idempotent).

    `CREATE TABLE IF NOT EXISTS` does NOT add new columns to a table that
    already exists, so a pre-existing older DB opened by newer code would lack
    columns the queries reference. This self-heals that case.
    """
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column in existing:
        return
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    except sqlite3.OperationalError:
        # Lost a race with a concurrent initializer; the column now exists.
        pass


def initialize_schema(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    # Forward-compat for DBs created by an older schema version that are opened
    # before the version-mismatch re-ingest replaces them (e.g. the JSON-missing
    # degraded path in app/dependencies.py).
    _ensure_column(conn, "notices", "content_markdown", "TEXT")
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
