import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_notice_service
from app.main import app
from app.schemas import Notice
from app.service import NoticeService


class MemoryRepository:
    def __init__(self, notices: list[Notice]) -> None:
        self.notices = notices

    async def list_all(self) -> list[Notice]:
        return self.notices

    async def get_by_id(self, notice_id: str) -> Notice | None:
        return next((notice for notice in self.notices if notice.id == notice_id), None)


def make_notice(
    notice_id: str,
    title: str,
    *,
    source: str,
    category: str | None = None,
    date: str = "2026-04-20",
) -> Notice:
    return Notice(
        id=notice_id,
        title=title,
        content=f"{title} 본문",
        source=source,
        sources=[source],
        category=category,
        date=date,
        summary=f"{title} 요약",
        tags=[category, source] if category else [source],
        attachments=[],
    )


@pytest.fixture()
def client() -> TestClient:
    notices = [
        make_notice(
            "common-academic",
            "수강신청 안내",
            source="한국항공대학교 공식 홈페이지",
            category="학사",
            date="2026-04-20",
        ),
        make_notice(
            "common-event",
            "헌혈 행사 안내",
            source="한국항공대학교 공식 홈페이지",
            category="일반공지",
            date="2026-04-22",
        ),
        make_notice(
            "cs",
            "AI 경진대회 안내",
            source="한국항공대학교 컴퓨터공학과",
            date="2026-04-23",
        ),
        make_notice(
            "graduate",
            "대학원 학사 안내",
            source="한국항공대학교 경영대학원",
            date="2026-04-24",
        ),
    ]
    app.dependency_overrides[get_notice_service] = lambda: NoticeService(MemoryRepository(notices))
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_get_notices_basic_shape(client: TestClient) -> None:
    response = client.get("/api/notices")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total", "page", "pageSize", "totalPages", "facets"}
    assert body["total"] == 4
    assert body["page"] == 1
    assert body["pageSize"] == 20
    assert isinstance(body["items"][0]["tags"], list)
    assert isinstance(body["items"][0]["attachments"], list)
    assert "전 구성원 공통" in body["facets"]["audienceGroups"]


def test_get_notices_accepts_audience_group_and_source_alias(client: TestClient) -> None:
    response = client.get(
        "/api/notices",
        params={
            "audience": "학부 재학생(학과/전공별)",
            "sourceGroup": "AI융합대",
            "source": "한국항공대학교 컴퓨터공학과",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == "cs"
    assert body["items"][0]["sourceGroups"] == ["AI융합대"]


def test_get_notices_search(client: TestClient) -> None:
    response = client.get("/api/notices", params={"q": "수강신청 정보 알려줘"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == "common-academic"


def test_get_notices_normalizes_invalid_pagination(client: TestClient) -> None:
    response = client.get("/api/notices", params={"page": "abc", "pageSize": "abc"})

    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["pageSize"] == 20


def test_get_notice_detail(client: TestClient) -> None:
    response = client.get("/api/notices/cs")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "cs"
    assert body["audienceGroup"] == "학부 재학생(학과/전공별)"
    assert body["sourceGroup"] == "AI융합대"


def test_get_notice_not_found(client: TestClient) -> None:
    response = client.get("/api/notices/missing")

    assert response.status_code == 404
    assert response.json() == {"error": "공지 항목을 찾을 수 없습니다."}


def test_post_chat_fallback(client: TestClient) -> None:
    response = client.post("/api/chat", json={"question": "수강신청 알려줘"})

    assert response.status_code == 200
    body = response.json()
    assert body["usedFallback"] is True
    assert body["model"] == "local-fallback"
    assert body["references"][0]["id"] == "common-academic"
    assert "OpenAI API 키가 없어" in body["answer"]


def test_post_chat_rejects_empty_question(client: TestClient) -> None:
    response = client.post("/api/chat", json={"question": "   "})

    assert response.status_code == 400
    assert response.json() == {"error": "question 필드는 필수입니다."}


def test_post_chat_rejects_missing_question(client: TestClient) -> None:
    response = client.post("/api/chat", json={})

    assert response.status_code == 400
    assert response.json() == {"error": "question 필드는 필수입니다."}
