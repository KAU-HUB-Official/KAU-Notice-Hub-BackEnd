"""카카오 로그인 사용자·북마크 저장소.

공지 DB(NOTICE_DB_PATH)는 크롤링 때마다 os.replace()로 통째로 교체되므로 사용자
데이터는 별도 SQLite 파일(USER_DB_PATH)에 둔다. 교체 대상이 아니라서 chat_log처럼
WAL을 쓰고, busy_timeout으로 워커 간 쓰기 경합을 기다린다.

카카오 회원번호(kakao_id)는 로그인 시 사용자를 찾는 데만 쓰고 API 응답에는 내부
ID(id)만 내보낸다.

북마크는 공지 ID와 함께 북마크 시점의 제목·URL·출처·날짜 사본을 저장한다. 공지가
1년이 지나 스냅샷에서 빠져도 북마크 목록에 제목과 원문 링크를 보여주기 위해서다.
사용자를 삭제하면 외래키 ON DELETE CASCADE로 북마크도 함께 지워진다.
"""

from __future__ import annotations

import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        kakao_id TEXT NOT NULL UNIQUE,
        nickname TEXT,
        created_at TEXT NOT NULL,
        last_login_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bookmarks (
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        notice_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        title TEXT NOT NULL,
        url TEXT,
        source TEXT,
        date TEXT,
        PRIMARY KEY (user_id, notice_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_bookmarks_user_created "
    "ON bookmarks(user_id, created_at DESC)",
)

_init_lock = threading.Lock()
_initialized: set[str] = set()


class UserStoreError(RuntimeError):
    """사용자 DB 읽기·쓰기 실패. 상세 원인은 서버 로그에만 남긴다."""


class BookmarkLimitExceeded(Exception):
    """사용자당 북마크 상한에 도달했다."""


@dataclass(frozen=True)
class UserRecord:
    id: str
    kakao_id: str
    nickname: str | None


@dataclass(frozen=True)
class BookmarkRecord:
    notice_id: str
    bookmarked_at: str
    title: str
    url: str | None
    source: str | None
    date: str | None


def _connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_initialized(db_path: str | Path) -> None:
    key = str(Path(db_path).expanduser().resolve())
    if key in _initialized:
        return
    with _init_lock:
        if key in _initialized:
            return
        conn = _connect(db_path)
        try:
            for statement in SCHEMA_STATEMENTS:
                conn.execute(statement)
        finally:
            conn.close()
        _initialized.add(key)


def _open(db_path: str | Path) -> sqlite3.Connection:
    try:
        _ensure_initialized(db_path)
        return _connect(db_path)
    except sqlite3.Error as exc:
        raise UserStoreError("사용자 DB를 열지 못했습니다.") from exc


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_user_id() -> str:
    return f"u_{secrets.token_hex(8)}"


def _to_record(row: sqlite3.Row) -> UserRecord:
    return UserRecord(
        id=row["id"],
        kakao_id=row["kakao_id"],
        nickname=row["nickname"],
    )


def upsert_kakao_user(
    db_path: str | Path,
    *,
    kakao_id: str,
    nickname: str | None,
) -> UserRecord:
    """카카오 회원번호로 사용자를 찾아 닉네임을 갱신하고, 없으면 새로 만든다."""
    now = _now_iso()
    conn = _open(db_path)
    try:
        row = conn.execute(
            """
            INSERT INTO users (
                id, kakao_id, nickname, created_at, last_login_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(kakao_id) DO UPDATE SET
                nickname = excluded.nickname,
                last_login_at = excluded.last_login_at
            RETURNING id, kakao_id, nickname
            """,
            (_new_user_id(), kakao_id, nickname, now, now),
        ).fetchone()
    except sqlite3.Error as exc:
        raise UserStoreError("사용자를 저장하지 못했습니다.") from exc
    finally:
        conn.close()
    return _to_record(row)


def get_user(db_path: str | Path, user_id: str) -> UserRecord | None:
    conn = _open(db_path)
    try:
        row = conn.execute(
            "SELECT id, kakao_id, nickname FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        raise UserStoreError("사용자를 조회하지 못했습니다.") from exc
    finally:
        conn.close()
    return _to_record(row) if row else None


def delete_user(db_path: str | Path, user_id: str) -> None:
    """사용자를 삭제한다. 사용자에 딸린 데이터는 외래키 ON DELETE CASCADE로 함께 지운다."""
    conn = _open(db_path)
    try:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    except sqlite3.Error as exc:
        raise UserStoreError("사용자를 삭제하지 못했습니다.") from exc
    finally:
        conn.close()


_BOOKMARK_COLUMNS = "notice_id, created_at, title, url, source, date"


def _to_bookmark(row: sqlite3.Row) -> BookmarkRecord:
    return BookmarkRecord(
        notice_id=row["notice_id"],
        bookmarked_at=row["created_at"],
        title=row["title"],
        url=row["url"],
        source=row["source"],
        date=row["date"],
    )


def get_bookmark(
    db_path: str | Path, user_id: str, notice_id: str
) -> BookmarkRecord | None:
    conn = _open(db_path)
    try:
        row = conn.execute(
            f"SELECT {_BOOKMARK_COLUMNS} FROM bookmarks WHERE user_id = ? AND notice_id = ?",
            (user_id, notice_id),
        ).fetchone()
    except sqlite3.Error as exc:
        raise UserStoreError("북마크를 조회하지 못했습니다.") from exc
    finally:
        conn.close()
    return _to_bookmark(row) if row else None


def add_bookmark(
    db_path: str | Path,
    user_id: str,
    *,
    notice_id: str,
    title: str,
    url: str | None,
    source: str | None,
    date: str | None,
    max_count: int,
) -> tuple[BookmarkRecord, bool]:
    """북마크를 추가하고 (북마크, 새로 만들었는지)를 돌려준다.

    이미 있으면 그대로 돌려준다(멱등). 상한 확인과 추가를 한 트랜잭션으로 묶어
    동시 요청으로 상한을 넘지 않게 한다.
    """
    conn = _open(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                f"SELECT {_BOOKMARK_COLUMNS} FROM bookmarks "
                "WHERE user_id = ? AND notice_id = ?",
                (user_id, notice_id),
            ).fetchone()
            if row:
                conn.execute("COMMIT")
                return _to_bookmark(row), False

            (count,) = conn.execute(
                "SELECT COUNT(*) FROM bookmarks WHERE user_id = ?", (user_id,)
            ).fetchone()
            if count >= max_count:
                conn.execute("ROLLBACK")
                raise BookmarkLimitExceeded()

            row = conn.execute(
                f"""
                INSERT INTO bookmarks (
                    user_id, notice_id, created_at, title, url, source, date
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                RETURNING {_BOOKMARK_COLUMNS}
                """,
                (user_id, notice_id, _now_iso(), title, url, source, date),
            ).fetchone()
            conn.execute("COMMIT")
        except sqlite3.Error:
            conn.execute("ROLLBACK")
            raise
    except sqlite3.Error as exc:
        raise UserStoreError("북마크를 저장하지 못했습니다.") from exc
    finally:
        conn.close()
    return _to_bookmark(row), True


def remove_bookmark(db_path: str | Path, user_id: str, notice_id: str) -> None:
    conn = _open(db_path)
    try:
        conn.execute(
            "DELETE FROM bookmarks WHERE user_id = ? AND notice_id = ?",
            (user_id, notice_id),
        )
    except sqlite3.Error as exc:
        raise UserStoreError("북마크를 삭제하지 못했습니다.") from exc
    finally:
        conn.close()


def list_bookmarks(
    db_path: str | Path, user_id: str, *, page: int, page_size: int
) -> tuple[list[BookmarkRecord], int, int]:
    """최근에 북마크한 순서로 한 페이지를 읽어 (항목, 전체 개수, 실제 페이지)를 돌려준다.

    공지 목록과 같이, 범위를 넘는 page는 마지막 페이지로 맞춘다.
    """
    conn = _open(db_path)
    try:
        (total,) = conn.execute(
            "SELECT COUNT(*) FROM bookmarks WHERE user_id = ?", (user_id,)
        ).fetchone()
        current_page = min(page, max(1, -(-total // page_size)))
        # created_at은 초 단위라 같은 초에 추가한 북마크는 rowid(삽입 순서)로 정렬한다.
        rows = conn.execute(
            f"SELECT {_BOOKMARK_COLUMNS} FROM bookmarks WHERE user_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
            (user_id, page_size, (current_page - 1) * page_size),
        ).fetchall()
    except sqlite3.Error as exc:
        raise UserStoreError("북마크 목록을 조회하지 못했습니다.") from exc
    finally:
        conn.close()
    return [_to_bookmark(row) for row in rows], total, current_page


def list_bookmark_ids(db_path: str | Path, user_id: str) -> list[str]:
    conn = _open(db_path)
    try:
        rows = conn.execute(
            "SELECT notice_id FROM bookmarks WHERE user_id = ? "
            "ORDER BY created_at DESC, rowid DESC",
            (user_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        raise UserStoreError("북마크 목록을 조회하지 못했습니다.") from exc
    finally:
        conn.close()
    return [row["notice_id"] for row in rows]
