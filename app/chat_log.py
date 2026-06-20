"""챗봇 Q/A 세션 로깅 (평가셋·개선용).

운영 notice DB와 **분리된** 별도 SQLite 파일에, 대화 한 턴(메시지)을 한 행으로
append만 한다. 세션 전문을 매번 다시 보내거나 upsert로 덮어쓰지 않는다:

- 사용자 입력이 오면 user 행 1개 INSERT
- LLM 답변이 나오면 assistant 행 1개 INSERT (references·model·fallback 포함)

세션은 `session_id`로 묶이고, 읽을 때 `ORDER BY id`로 순서를 복원한다. 저장은
응답 경로 밖(백그라운드)에서 돌고, 실패해도 챗봇 응답을 절대 깨뜨리지 않는다
(best-effort, 예외는 로그만 남긴다).

이 DB는 ingest의 os.replace() 스왑 대상이 아닌 전용 append 파일이라, notice DB와
달리 WAL을 쓴다(잦은 동시 INSERT에 유리, busy_timeout으로 쓰기 경합 재시도).
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        references_json TEXT,
        used_fallback INTEGER,
        model TEXT,
        audience_group TEXT,
        source_group TEXT,
        source TEXT,
        category TEXT,
        department TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, id)",
)

_init_lock = threading.Lock()
_initialized: set[str] = set()

# fire_and_forget 태스크 참조를 들고 있어 GC로 중간에 취소되지 않게 한다.
_pending: set[asyncio.Task[Any]] = set()


def _connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insert_message(
    db_path: str | Path,
    *,
    session_id: str,
    role: str,
    content: str,
    references_json: str | None = None,
    used_fallback: bool | None = None,
    model: str | None = None,
    filters: dict[str, Any] | None = None,
) -> None:
    _ensure_initialized(db_path)
    flt = filters or {}
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO chat_messages (
                session_id, role, content, created_at,
                references_json, used_fallback, model,
                audience_group, source_group, source, category, department
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                role,
                content,
                _now_iso(),
                references_json,
                None if used_fallback is None else int(used_fallback),
                model,
                flt.get("audience_group"),
                flt.get("source_group"),
                flt.get("source"),
                flt.get("category"),
                flt.get("department"),
            ),
        )
    finally:
        conn.close()


def record_user_message(
    db_path: str | Path,
    session_id: str,
    content: str,
    *,
    filters: dict[str, Any] | None = None,
) -> None:
    """사용자 입력 한 턴을 저장한다. 실패해도 예외를 삼킨다(best-effort)."""
    try:
        _insert_message(
            db_path,
            session_id=session_id,
            role="user",
            content=content,
            filters=filters,
        )
    except Exception:  # noqa: BLE001 - 로깅 실패가 챗봇 응답을 깨선 안 된다
        logger.warning("chat log: failed to record user message", exc_info=True)


def record_assistant_message(
    db_path: str | Path,
    session_id: str,
    content: str,
    *,
    references: list[dict[str, Any]] | None = None,
    used_fallback: bool | None = None,
    model: str | None = None,
) -> None:
    """LLM 답변 한 턴을 references·model·fallback과 함께 저장한다(best-effort)."""
    try:
        references_json = (
            json.dumps(references, ensure_ascii=False) if references else None
        )
        _insert_message(
            db_path,
            session_id=session_id,
            role="assistant",
            content=content,
            references_json=references_json,
            used_fallback=used_fallback,
            model=model,
        )
    except Exception:  # noqa: BLE001
        logger.warning("chat log: failed to record assistant message", exc_info=True)


def fire_and_forget(fn: Callable[..., None], *args: Any, **kwargs: Any) -> None:
    """동기 쓰기 함수를 워커 스레드에서 비차단으로 돌린다(스트리밍 경로용).

    실행 중인 이벤트 루프가 없으면(테스트 등) 그 자리에서 동기로 실행한다.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        fn(*args, **kwargs)
        return

    async def _runner() -> None:
        await asyncio.to_thread(fn, *args, **kwargs)

    task = loop.create_task(_runner())
    _pending.add(task)
    task.add_done_callback(_pending.discard)


def read_session_messages(
    db_path: str | Path, session_id: str
) -> list[dict[str, Any]]:
    """한 세션의 메시지를 시간순으로 읽는다. (테스트·평가셋 추출용)"""
    path = Path(db_path).expanduser()
    if not path.exists():
        return []
    conn = _connect(path)
    try:
        rows = conn.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]
