"""챗봇 Q/A 세션 로깅 (app/chat_log.py + /api/chat 훅) 테스트."""

from __future__ import annotations

import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from app import chat_log
from app.config import get_settings
from app.dependencies import get_notice_service
from app.main import app
from app.repository import NoticeSearchQuery, NoticeSearchResult
from app.schemas import Notice
from app.service import NoticeService
from app.service_pipeline import legacy_search


# ---------- 단위: chat_log 모듈 ----------


def test_record_and_read_session(tmp_path) -> None:
    db = tmp_path / "chat.db"
    chat_log.record_user_message(db, "s1", "장학금 신청", filters={"category": "장학"})
    chat_log.record_assistant_message(
        db,
        "s1",
        "장학금은 6월 30일까지입니다.",
        references=[{"id": "n1", "title": "장학금 공지"}],
        used_fallback=False,
        model="gpt-4.1-mini",
    )

    rows = chat_log.read_session_messages(db, "s1")
    assert [r["role"] for r in rows] == ["user", "assistant"]

    user_row = rows[0]
    assert user_row["content"] == "장학금 신청"
    assert user_row["category"] == "장학"
    assert user_row["references_json"] is None

    assistant_row = rows[1]
    assert assistant_row["model"] == "gpt-4.1-mini"
    assert assistant_row["used_fallback"] == 0
    assert json.loads(assistant_row["references_json"])[0]["id"] == "n1"


def test_append_only_keeps_turn_order(tmp_path) -> None:
    db = tmp_path / "chat.db"
    for i in range(3):
        chat_log.record_user_message(db, "s1", f"질문{i}")
        chat_log.record_assistant_message(db, "s1", f"답변{i}")

    rows = chat_log.read_session_messages(db, "s1")
    assert [r["content"] for r in rows] == [
        "질문0", "답변0", "질문1", "답변1", "질문2", "답변2"
    ]


def test_sessions_are_isolated(tmp_path) -> None:
    db = tmp_path / "chat.db"
    chat_log.record_user_message(db, "a", "a-질문")
    chat_log.record_user_message(db, "b", "b-질문")
    assert [r["content"] for r in chat_log.read_session_messages(db, "a")] == ["a-질문"]
    assert [r["content"] for r in chat_log.read_session_messages(db, "b")] == ["b-질문"]


def test_read_missing_db_returns_empty(tmp_path) -> None:
    assert chat_log.read_session_messages(tmp_path / "nope.db", "x") == []


def test_assistant_retrieval_roundtrip(tmp_path) -> None:
    db = tmp_path / "chat.db"
    trace = {
        "mode": "search",
        "triage_keywords": ["장학금"],
        "candidates": [{"rank": 1, "id": "n1", "title": "장학금 공지"}],
        "rerank_outcome": "selected",
        "latency_ms": {"triage": 12, "search": 3, "rerank": 0, "retrieval_total": 15},
    }
    chat_log.record_assistant_message(db, "s1", "답변", retrieval=trace)

    row = chat_log.read_session_messages(db, "s1")[0]
    assert json.loads(row["retrieval_json"]) == trace


def test_assistant_without_retrieval_stores_null(tmp_path) -> None:
    db = tmp_path / "chat.db"
    chat_log.record_assistant_message(db, "s1", "답변", model="gpt-4.1-mini")

    row = chat_log.read_session_messages(db, "s1")[0]
    assert row["retrieval_json"] is None


def test_migration_adds_retrieval_column_to_existing_db(tmp_path) -> None:
    """retrieval_json이 없는 구 스키마 DB도 첫 저장 때 컬럼이 추가되어야 한다."""
    db = tmp_path / "chat.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE chat_messages (
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
        """
    )
    conn.execute(
        "INSERT INTO chat_messages (session_id, role, content, created_at) "
        "VALUES ('s1', 'user', '기존 행', '2026-09-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    chat_log.record_assistant_message(db, "s1", "답변", retrieval={"mode": "search"})

    rows = chat_log.read_session_messages(db, "s1")
    # 기존 행은 그대로 남고(새 컬럼은 NULL), 새 행에만 trace가 붙는다.
    assert [r["content"] for r in rows] == ["기존 행", "답변"]
    assert rows[0]["retrieval_json"] is None
    assert json.loads(rows[1]["retrieval_json"]) == {"mode": "search"}


def test_record_swallows_errors(tmp_path) -> None:
    # 디렉토리를 db 경로로 주면 sqlite 연결이 실패하지만 예외를 삼켜야 한다.
    chat_log.record_user_message(tmp_path, "s", "내용")  # raise 하면 실패


# ---------- 통합: /api/chat 로깅 훅 ----------


class _MemoryRepo:
    def __init__(self, notices: list[Notice]) -> None:
        self.notices = notices

    async def list_all(self) -> list[Notice]:
        return self.notices

    async def get_by_id(self, notice_id: str) -> Notice | None:
        return next((n for n in self.notices if n.id == notice_id), None)

    async def search(self, query: NoticeSearchQuery) -> NoticeSearchResult:
        return legacy_search(self.notices, query)


def _notice() -> Notice:
    return Notice(
        id="n1",
        title="장학금 신청 안내",
        content="장학금 신청 본문",
        source="한국항공대학교 공식 홈페이지",
        sources=["한국항공대학교 공식 홈페이지"],
        category="장학",
        date="2026-04-20",
        tags=["장학"],
        attachments=[],
    )


def _override_service() -> None:
    app.dependency_overrides[get_notice_service] = lambda: NoticeService(
        _MemoryRepo([_notice()])
    )


def test_chat_logs_user_and_assistant_turn(tmp_path, monkeypatch) -> None:
    settings = get_settings()
    db = tmp_path / "chat_sessions.db"
    monkeypatch.setattr(settings, "chat_logging_enabled", True)
    monkeypatch.setattr(settings, "chat_log_db_path", db)
    _override_service()
    try:
        with TestClient(app) as client:
            res = client.post(
                "/api/chat",
                json={"question": "장학금 신청", "sessionId": "sess-1", "category": "장학"},
            )
        assert res.status_code == 200
    finally:
        app.dependency_overrides.clear()

    rows = chat_log.read_session_messages(db, "sess-1")
    assert [r["role"] for r in rows] == ["user", "assistant"]
    assert rows[0]["content"] == "장학금 신청"
    assert rows[0]["category"] == "장학"
    assert rows[1]["model"]  # local-fallback 등 비어있지 않음
    assert rows[0]["retrieval_json"] is None  # 사용자 턴에는 trace 없음

    retrieval = json.loads(rows[1]["retrieval_json"])
    assert retrieval["mode"]
    assert "candidates" in retrieval
    assert "latency_ms" in retrieval


def _wait_for_rows(db, session_id: str, count: int, timeout: float = 3.0) -> list:
    """스트림 경로의 저장은 백그라운드 태스크라 잠시 기다렸다 읽는다."""
    deadline = time.monotonic() + timeout
    rows = chat_log.read_session_messages(db, session_id)
    while len(rows) < count and time.monotonic() < deadline:
        time.sleep(0.02)
        rows = chat_log.read_session_messages(db, session_id)
    return rows


def test_chat_stream_logs_turn_with_retrieval_trace(tmp_path, monkeypatch) -> None:
    """스트림 경로도 assistant 턴에 trace를 남기고, SSE로는 내부 이벤트를 보내지 않는다."""
    settings = get_settings()
    db = tmp_path / "chat_sessions.db"
    monkeypatch.setattr(settings, "chat_logging_enabled", True)
    monkeypatch.setattr(settings, "chat_log_db_path", db)
    _override_service()
    try:
        with TestClient(app) as client:
            res = client.post(
                "/api/chat/stream",
                json={"question": "장학금 신청", "sessionId": "sess-stream"},
            )
            assert res.status_code == 200
            body = res.text
            rows = _wait_for_rows(db, "sess-stream", 2)
    finally:
        app.dependency_overrides.clear()

    # 내부 이벤트는 클라이언트로 나가지 않는다.
    assert "_retrieval_trace" not in body
    assert '"type": "search_completed"' in body

    # 스트림 경로는 user/assistant 저장이 각각 별도 fire_and_forget 태스크라
    # INSERT 순서(=id 순서)가 보장되지 않는다. 여기서는 두 턴이 모두 남고
    # assistant 턴에 trace가 붙는지만 본다.
    assert sorted(r["role"] for r in rows) == ["assistant", "user"]
    assistant_row = next(r for r in rows if r["role"] == "assistant")
    retrieval = json.loads(assistant_row["retrieval_json"])
    assert retrieval["mode"]
    assert "candidates" in retrieval
    assert "latency_ms" in retrieval


def test_chat_without_session_id_is_not_logged(tmp_path, monkeypatch) -> None:
    settings = get_settings()
    db = tmp_path / "chat_sessions.db"
    monkeypatch.setattr(settings, "chat_logging_enabled", True)
    monkeypatch.setattr(settings, "chat_log_db_path", db)
    _override_service()
    try:
        with TestClient(app) as client:
            res = client.post("/api/chat", json={"question": "장학금 신청"})
        assert res.status_code == 200
    finally:
        app.dependency_overrides.clear()

    assert chat_log.read_session_messages(db, "anything") == []


def test_chat_logging_disabled_writes_nothing(tmp_path, monkeypatch) -> None:
    settings = get_settings()
    db = tmp_path / "chat_sessions.db"
    monkeypatch.setattr(settings, "chat_logging_enabled", False)
    monkeypatch.setattr(settings, "chat_log_db_path", db)
    _override_service()
    try:
        with TestClient(app) as client:
            res = client.post(
                "/api/chat", json={"question": "장학금 신청", "sessionId": "s"}
            )
        assert res.status_code == 200
    finally:
        app.dependency_overrides.clear()

    assert chat_log.read_session_messages(db, "s") == []
