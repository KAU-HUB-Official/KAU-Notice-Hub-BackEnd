"""챗봇 요청의 userGroup(공지 대상)으로 검색을 거르고 로그에 남기는지 본다. OpenAI는 부르지 않는다."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import chat_log
from app.config import get_settings
from app.dependencies import get_notice_service
from app.ingest import ingest_json_snapshot
from app.main import app
from app.repository import NoticeSearchQuery, NoticeSearchResult
from app.schemas import NoticeFacets
from app.service import NoticeQuery, NoticeService
from app.sqlite_repository import SqliteNoticeRepository


def _notice(notice_id: str, title: str, seq: int) -> dict:
    return {
        "id": notice_id,
        "title": title,
        "content": f"{title} 본문",
        "published_at": f"2026-10-{10 + seq:02d}",
        "original_url": f"https://kau.ac.kr/a.php?seq={seq}",
    }


def _label(seq: int, audiences: list[str]) -> str:
    return json.dumps(
        {"url": f"https://kau.ac.kr/a.php?seq={seq}", "audiences": audiences, "excludes": []},
        ensure_ascii=False,
    )


@pytest.fixture()
def chat_env(tmp_path: Path, monkeypatch):
    json_path = tmp_path / "notices.json"
    labels_path = tmp_path / "labels.jsonl"
    db_path = tmp_path / "notices.db"
    json_path.write_text(
        json.dumps(
            [
                _notice("undergrad", "학부 장학금 신청 안내", 1),
                _notice("grad", "대학원 장학금 신청 안내", 2),
                _notice("unlabeled", "장학금 신청 기간 안내", 3),
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    labels_path.write_text(
        _label(1, ["학부재학생"]) + "\n" + _label(2, ["일반대학원생"]) + "\n", encoding="utf-8"
    )
    ingest_json_snapshot(json_path=json_path, db_path=db_path, labels_path=labels_path)

    settings = get_settings()
    log_db = tmp_path / "chat_sessions.db"
    # 검색 분기·답변 LLM을 끄고 로컬 경로로만 돌린다(OpenAI 호출 없음).
    monkeypatch.setattr(settings, "rag_enabled", False)
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "chat_logging_enabled", True)
    monkeypatch.setattr(settings, "chat_log_db_path", log_db)
    app.dependency_overrides[get_notice_service] = lambda: NoticeService(
        SqliteNoticeRepository(db_path)
    )
    try:
        yield log_db
    finally:
        app.dependency_overrides.clear()


def _reference_ids(body: dict) -> set[str]:
    return {reference["id"] for reference in body["references"]}


def test_user_group_filters_chat_references(chat_env) -> None:
    with TestClient(app) as client:
        grad = client.post(
            "/api/chat", json={"question": "장학금 신청", "userGroup": "일반대학원생"}
        ).json()
        everyone = client.post("/api/chat", json={"question": "장학금 신청"}).json()

    assert _reference_ids(grad) == {"grad", "unlabeled"}
    assert _reference_ids(everyone) == {"undergrad", "grad", "unlabeled"}


def test_unknown_user_group_does_not_filter_and_is_not_logged(chat_env) -> None:
    with TestClient(app) as client:
        body = client.post(
            "/api/chat",
            json={"question": "장학금 신청", "userGroup": "모르는값", "sessionId": "s-unknown"},
        ).json()

    assert _reference_ids(body) == {"undergrad", "grad", "unlabeled"}
    rows = chat_log.read_session_messages(chat_env, "s-unknown")
    assert [row["user_group"] for row in rows] == [None, None]


def test_chat_logs_user_group_and_trace_target(chat_env) -> None:
    with TestClient(app) as client:
        client.post(
            "/api/chat",
            json={"question": "장학금 신청", "userGroup": "학부재학생", "sessionId": "s-1"},
        )

    rows = chat_log.read_session_messages(chat_env, "s-1")
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assert [row["user_group"] for row in rows] == ["학부재학생", "학부재학생"]
    assert json.loads(rows[1]["retrieval_json"])["target"] == "학부재학생"


def _wait_for_rows(db: Path, session_id: str, count: int, timeout: float = 3.0) -> list:
    deadline = time.monotonic() + timeout
    rows = chat_log.read_session_messages(db, session_id)
    while len(rows) < count and time.monotonic() < deadline:
        time.sleep(0.02)
        rows = chat_log.read_session_messages(db, session_id)
    return rows


def test_chat_stream_filters_and_logs_user_group(chat_env) -> None:
    with TestClient(app) as client:
        res = client.post(
            "/api/chat/stream",
            json={"question": "장학금 신청", "userGroup": "일반대학원생", "sessionId": "s-stream"},
        )
        assert res.status_code == 200
        rows = _wait_for_rows(chat_env, "s-stream", 2)

    completed = [
        json.loads(line[len("data: ") :])
        for line in res.text.splitlines()
        if line.startswith("data: ") and '"search_completed"' in line
    ]
    assert completed, res.text
    assert {reference["id"] for reference in completed[0]["references"]} == {"grad", "unlabeled"}
    assert [row["user_group"] for row in rows] == ["일반대학원생", "일반대학원생"]


class _CapturingRepository:
    def __init__(self) -> None:
        self.queries: list[NoticeSearchQuery] = []

    async def list_all(self):
        return []

    async def get_by_id(self, notice_id):
        return None

    async def search(self, query: NoticeSearchQuery) -> NoticeSearchResult:
        self.queries.append(query)
        return NoticeSearchResult(items=[], total=0, facets=NoticeFacets())


def test_find_relevant_notices_keeps_target_in_search_and_latest_fallback() -> None:
    repository = _CapturingRepository()
    service = NoticeService(repository)

    asyncio.run(
        service.find_relevant_notices(
            "장학금", filters=NoticeQuery(target="특수대학원생"), fallback_to_latest=True
        )
    )

    assert [query.q for query in repository.queries] == ["장학금", None]
    assert [query.target for query in repository.queries] == ["특수대학원생", "특수대학원생"]


def test_migration_adds_user_group_column_to_existing_db(tmp_path: Path) -> None:
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
            department TEXT,
            retrieval_json TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO chat_messages (session_id, role, content, created_at) "
        "VALUES ('s1', 'user', '기존 행', '2026-10-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    chat_log.record_user_message(db, "s1", "새 질문", filters={"user_group": "교직원·기타"})

    rows = chat_log.read_session_messages(db, "s1")
    assert [(row["content"], row["user_group"]) for row in rows] == [
        ("기존 행", None),
        ("새 질문", "교직원·기타"),
    ]
