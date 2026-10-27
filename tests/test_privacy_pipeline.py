"""적재부터 응답까지 학번과 이름이 가려지는지 본다. 예시 이름과 학번은 지어낸 것이다.

단위 테스트(test_privacy.py, test_name_masking.py)는 마스킹 함수만 본다. 여기서는
본문이 실제로 지나가는 길(JSON → SQLite 적재 → 공지 API, 챗봇의 LLM 입력)에서
가려진 본문만 나가는지 확인한다. 이름은 가짜 모델로 찾는다.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.chat_service import build_context, build_rerank_list, fallback_answer
from app.config import get_settings
from app.dependencies import get_notice_service
from app.ingest import ingest_json_snapshot
from app.main import app
from app.schemas import Notice
from app.service import NoticeService
from app.sqlite_repository import SqliteNoticeRepository
from tests.fakes import FakeFinder

STUDENT_ID = "2017999928"
NAME = "홍길동"
PHONE = "02-300-0272"
BODY = "\n".join(
    [
        "캡스톤디자인 최우수상 수상자를 안내합니다.",
        "",
        "| 학번 | 성명 |",
        "| --- | --- |",
        f"| {STUDENT_ID} | {NAME} |",
        "",
        f"문의 : 교육성과관리센터 {PHONE}",
    ]
)


def assert_masked(text: str) -> None:
    assert STUDENT_ID not in text
    assert NAME not in text
    assert "2017○○○○28" in text
    assert "홍○○" in text
    assert PHONE in text


@pytest.fixture()
def client(tmp_path, masking_on):
    masking_on(FakeFinder(NAME))
    json_path = tmp_path / "notices.json"
    db_path = tmp_path / "notices.db"
    json_path.write_text(
        json.dumps(
            [
                {
                    "title": "캡스톤디자인 수상자 안내",
                    "content": BODY,
                    "source_name": "한국항공대학교 공식 홈페이지",
                    "category_raw": "학사",
                    "published_at": "2026-09-15",
                    "original_url": "https://example.com/notice/1",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ingest_json_snapshot(json_path=json_path, db_path=db_path)
    app.dependency_overrides[get_notice_service] = lambda: NoticeService(SqliteNoticeRepository(db_path))
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestIngestToApi:
    def test_공지_상세_응답의_본문이_가려진다(self, client):
        notice_id = client.get("/api/notices").json()["items"][0]["id"]
        response = client.get(f"/api/notices/{notice_id}")
        assert response.status_code == 200
        assert_masked(response.json()["content"])

    def test_목록_응답의_본문이_가려진다(self, client):
        assert_masked(client.get("/api/notices").json()["items"][0]["content"])

    @pytest.mark.parametrize("query", [STUDENT_ID, NAME])
    def test_학번과_이름으로_검색되지_않는다(self, client, query):
        assert client.get("/api/notices", params={"q": query}).json()["total"] == 0


class TestChatInputs:
    """본문 마스킹(PRIVACY_MASK_BODY)을 꺼서 원문이 저장돼 있어도 LLM 입력은 가려진다."""

    @pytest.fixture()
    def notice(self, masking_on, monkeypatch):
        masking_on(FakeFinder(NAME))
        monkeypatch.setattr(get_settings(), "privacy_mask_body", False)
        return Notice(id="n1", title="캡스톤디자인 수상자 안내", content=BODY, date="2026-09-15")

    def test_답변_컨텍스트(self, notice):
        assert_masked(build_context([notice]))

    def test_rerank_입력(self, notice):
        assert_masked(build_rerank_list([notice]))

    def test_LLM_없이_보여주는_발췌(self, notice):
        # 발췌는 120자로 자르므로 이름과 학번이 그 안에 들도록 앞부분만 쓴다.
        short = notice.model_copy(update={"content": f"수상자 {NAME} ({STUDENT_ID}) 문의 {PHONE}"})
        assert_masked(fallback_answer("수상자", [short]))
