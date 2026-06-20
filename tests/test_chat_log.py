"""챗봇 Q/A 세션 로깅 (app/chat_log.py + /api/chat 훅) 테스트."""

from __future__ import annotations

import json

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
        summary="장학금 요약",
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
