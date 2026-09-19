import pytest
from fastapi.testclient import TestClient

from app import user_store
from app.auth import issue_access_token
from app.config import get_settings
from app.dependencies import get_notice_service
from app.main import app
from app.repository import NoticeSearchQuery, NoticeSearchResult
from app.schemas import Notice
from app.service import NoticeService
from app.service_pipeline import legacy_search

SECRET = "s" * 32


class _MemoryRepo:
    def __init__(self, notices: list[Notice]) -> None:
        self.notices = notices

    async def list_all(self) -> list[Notice]:
        return self.notices

    async def get_by_id(self, notice_id: str) -> Notice | None:
        return next((n for n in self.notices if n.id == notice_id), None)

    async def search(self, query: NoticeSearchQuery) -> NoticeSearchResult:
        return legacy_search(self.notices, query)


def _notice(notice_id: str, title: str) -> Notice:
    return Notice(
        id=notice_id,
        title=title,
        content=f"{title} 본문",
        url=f"https://www.kau.ac.kr/notice/{notice_id}",
        source="한국항공대학교 공식 홈페이지",
        sources=["한국항공대학교 공식 홈페이지"],
        category="학사",
        date="2026-09-01",
        tags=["학사"],
        attachments=[],
    )


@pytest.fixture()
def env(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "jwt_secret", SECRET)
    monkeypatch.setattr(settings, "user_db_path", tmp_path / "users.db")
    monkeypatch.setattr(settings, "bookmark_max_per_user", 500)

    repo = _MemoryRepo(
        [_notice("aaaa000000000001", "수강신청 안내"), _notice("bbbb000000000002", "장학금 안내")]
    )
    app.dependency_overrides[get_notice_service] = lambda: NoticeService(repo)
    try:
        with TestClient(app) as client:
            yield client, repo, settings
    finally:
        app.dependency_overrides.clear()


def _login(settings, kakao_id: str = "1001") -> tuple[str, dict[str, str]]:
    user = user_store.upsert_kakao_user(
        settings.user_db_path, kakao_id=kakao_id, nickname="항공대생"
    )
    token = issue_access_token(user.id, secret=SECRET, expires_in=3600)
    return user.id, {"Authorization": f"Bearer {token}"}


def test_put_creates_bookmark_then_is_idempotent(env) -> None:
    client, _, settings = env
    _, headers = _login(settings)

    created = client.put("/api/bookmarks/aaaa000000000001", headers=headers)
    assert created.status_code == 201
    body = created.json()
    assert body["noticeId"] == "aaaa000000000001"
    assert body["notice"]["title"] == "수강신청 안내"
    assert body["saved"] == {
        "id": "aaaa000000000001",
        "title": "수강신청 안내",
        "url": "https://www.kau.ac.kr/notice/aaaa000000000001",
        "source": "한국항공대학교 공식 홈페이지",
        "date": "2026-09-01",
    }

    again = client.put("/api/bookmarks/aaaa000000000001", headers=headers)
    assert again.status_code == 200
    assert again.json()["bookmarkedAt"] == body["bookmarkedAt"]


def test_put_unknown_notice_returns_404(env) -> None:
    client, _, settings = env
    _, headers = _login(settings)

    res = client.put("/api/bookmarks/does-not-exist", headers=headers)

    assert res.status_code == 404
    assert res.json() == {"error": "공지 항목을 찾을 수 없습니다."}


def test_list_orders_newest_first_and_paginates(env) -> None:
    client, _, settings = env
    _, headers = _login(settings)
    client.put("/api/bookmarks/aaaa000000000001", headers=headers)
    client.put("/api/bookmarks/bbbb000000000002", headers=headers)

    first = client.get("/api/bookmarks?pageSize=1", headers=headers).json()
    second = client.get("/api/bookmarks?page=2&pageSize=1", headers=headers).json()
    beyond = client.get("/api/bookmarks?page=9&pageSize=1", headers=headers).json()

    assert [b["noticeId"] for b in first["items"]] == ["bbbb000000000002"]
    assert (first["total"], first["page"], first["pageSize"], first["totalPages"]) == (2, 1, 1, 2)
    assert [b["noticeId"] for b in second["items"]] == ["aaaa000000000001"]
    # 범위를 넘는 page는 마지막 페이지로 맞춘다(공지 목록과 같은 규칙).
    assert beyond["page"] == 2
    assert [b["noticeId"] for b in beyond["items"]] == ["aaaa000000000001"]


def test_list_is_empty_for_new_user(env) -> None:
    client, _, settings = env
    _, headers = _login(settings)

    body = client.get("/api/bookmarks", headers=headers).json()

    assert body == {"items": [], "total": 0, "page": 1, "pageSize": 20, "totalPages": 1}


def test_bookmark_survives_notice_removal(env) -> None:
    client, repo, settings = env
    _, headers = _login(settings)
    client.put("/api/bookmarks/aaaa000000000001", headers=headers)

    # 1년이 지나 공지가 스냅샷에서 빠진 경우
    repo.notices = [n for n in repo.notices if n.id != "aaaa000000000001"]

    items = client.get("/api/bookmarks", headers=headers).json()["items"]
    assert len(items) == 1
    assert items[0]["notice"] is None
    assert items[0]["saved"]["title"] == "수강신청 안내"
    assert items[0]["saved"]["url"] == "https://www.kau.ac.kr/notice/aaaa000000000001"

    # 이미 북마크한 공지는 스냅샷에 없어도 404가 아니라 200이다.
    res = client.put("/api/bookmarks/aaaa000000000001", headers=headers)
    assert res.status_code == 200
    assert res.json()["notice"] is None


def test_ids_lists_all_bookmarked_notice_ids(env) -> None:
    client, _, settings = env
    _, headers = _login(settings)
    client.put("/api/bookmarks/aaaa000000000001", headers=headers)
    client.put("/api/bookmarks/bbbb000000000002", headers=headers)

    res = client.get("/api/bookmarks/ids", headers=headers)

    assert res.status_code == 200
    assert res.json() == {"noticeIds": ["bbbb000000000002", "aaaa000000000001"]}


def test_delete_is_idempotent(env) -> None:
    client, _, settings = env
    _, headers = _login(settings)
    client.put("/api/bookmarks/aaaa000000000001", headers=headers)

    first = client.delete("/api/bookmarks/aaaa000000000001", headers=headers)
    second = client.delete("/api/bookmarks/aaaa000000000001", headers=headers)

    assert first.status_code == 204 and first.content == b""
    assert second.status_code == 204
    assert client.get("/api/bookmarks/ids", headers=headers).json() == {"noticeIds": []}


def test_put_rejects_new_bookmark_over_limit(env, monkeypatch) -> None:
    client, _, settings = env
    monkeypatch.setattr(settings, "bookmark_max_per_user", 1)
    _, headers = _login(settings)
    client.put("/api/bookmarks/aaaa000000000001", headers=headers)

    over = client.put("/api/bookmarks/bbbb000000000002", headers=headers)
    existing = client.put("/api/bookmarks/aaaa000000000001", headers=headers)

    assert over.status_code == 409
    assert over.json() == {"error": "북마크는 최대 1개까지 저장할 수 있습니다."}
    # 상한에 도달해도 이미 있는 북마크 재요청은 성공한다.
    assert existing.status_code == 200


def test_bookmarks_are_per_user(env) -> None:
    client, _, settings = env
    _, alice = _login(settings, kakao_id="1001")
    _, bob = _login(settings, kakao_id="2002")
    client.put("/api/bookmarks/aaaa000000000001", headers=alice)

    assert client.get("/api/bookmarks/ids", headers=bob).json() == {"noticeIds": []}
    # 다른 사용자의 삭제 요청은 내 북마크에 영향을 주지 않는다.
    client.delete("/api/bookmarks/aaaa000000000001", headers=bob)
    assert client.get("/api/bookmarks/ids", headers=alice).json() == {
        "noticeIds": ["aaaa000000000001"]
    }


def test_delete_me_removes_bookmarks(env) -> None:
    client, _, settings = env
    user_id, headers = _login(settings)
    client.put("/api/bookmarks/aaaa000000000001", headers=headers)

    assert client.delete("/api/me", headers=headers).status_code == 204

    assert user_store.list_bookmark_ids(settings.user_db_path, user_id) == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/bookmarks"),
        ("get", "/api/bookmarks/ids"),
        ("put", "/api/bookmarks/aaaa000000000001"),
        ("delete", "/api/bookmarks/aaaa000000000001"),
    ],
)
def test_bookmark_endpoints_require_login(env, method, path) -> None:
    client, _, _ = env

    res = client.request(method, path)

    assert res.status_code == 401
    assert res.json() == {"error": "로그인이 필요합니다."}
