"""카카오 로그인 사용자 저장소.

공지 DB(NOTICE_DB_PATH)는 크롤링 때마다 os.replace()로 통째로 교체되므로 사용자
데이터는 별도 SQLite 파일(USER_DB_PATH)에 둔다. 교체 대상이 아니라서 chat_log처럼
WAL을 쓰고, busy_timeout으로 워커 간 쓰기 경합을 기다린다.

카카오 회원번호(kakao_id)는 로그인 시 사용자를 찾는 데만 쓰고 API 응답에는 내부
ID(id)만 내보낸다.
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
)

_init_lock = threading.Lock()
_initialized: set[str] = set()


class UserStoreError(RuntimeError):
    """사용자 DB 읽기·쓰기 실패. 상세 원인은 서버 로그에만 남긴다."""


@dataclass(frozen=True)
class UserRecord:
    id: str
    kakao_id: str
    nickname: str | None


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
