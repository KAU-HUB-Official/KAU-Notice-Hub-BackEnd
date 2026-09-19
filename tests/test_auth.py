import pytest
from fastapi.testclient import TestClient

from app import kakao
from app.api import auth as auth_api
from app.auth import issue_access_token
from app.config import get_settings
from app.main import app

SECRET = "s" * 32
REDIRECT_URI = "http://localhost:3000/auth/kakao/callback"


@pytest.fixture()
def login_env(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "kakao_rest_api_key", "test-rest-key")
    monkeypatch.setattr(settings, "kakao_client_secret", None)
    monkeypatch.setattr(settings, "kakao_allowed_redirect_uris", REDIRECT_URI)
    monkeypatch.setattr(settings, "jwt_secret", SECRET)
    monkeypatch.setattr(settings, "jwt_expire_seconds", 3600)
    monkeypatch.setattr(settings, "user_db_path", tmp_path / "users.db")
    return settings


@pytest.fixture()
def kakao_calls(monkeypatch):
    """카카오 API 대신 code별로 정해 둔 프로필(또는 예외)을 돌려준다."""
    calls: list[dict] = []
    results: dict[str, object] = {
        "code-a": kakao.KakaoProfile("1001", "항공대생"),
    }

    def fake(code, redirect_uri, *, client_id, client_secret=None):
        calls.append(
            {
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            }
        )
        result = results[code]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(auth_api.kakao, "fetch_profile_by_code", fake)
    return calls, results


def _login(client: TestClient, code: str = "code-a"):
    return client.post(
        "/api/auth/kakao", json={"code": code, "redirectUri": REDIRECT_URI}
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_kakao_login_issues_token_and_creates_user(login_env, kakao_calls) -> None:
    calls, _ = kakao_calls
    with TestClient(app) as client:
        res = _login(client)
        assert res.status_code == 200
        body = res.json()

        assert body["tokenType"] == "Bearer"
        assert body["expiresIn"] == 3600
        assert body["user"]["id"].startswith("u_")
        assert body["user"] == {"id": body["user"]["id"], "nickname": "항공대생"}
        # 카카오 회원번호는 응답에 내보내지 않는다.
        assert "1001" not in res.text

        me = client.get("/api/me", headers=_auth(body["accessToken"]))
        assert me.status_code == 200
        assert me.json() == body["user"]

    assert calls == [
        {
            "code": "code-a",
            "redirect_uri": REDIRECT_URI,
            "client_id": "test-rest-key",
            "client_secret": None,
        }
    ]


def test_kakao_login_reuses_user_and_refreshes_nickname(login_env, kakao_calls) -> None:
    _, results = kakao_calls
    results["code-b"] = kakao.KakaoProfile("1001", "새 닉네임")

    with TestClient(app) as client:
        first = _login(client, "code-a").json()["user"]
        second = _login(client, "code-b").json()["user"]

    assert second["id"] == first["id"]
    assert second["nickname"] == "새 닉네임"


@pytest.mark.parametrize(
    "overrides",
    [
        {"kakao_rest_api_key": None},
        {"kakao_allowed_redirect_uris": ""},
        {"jwt_secret": None},
        {"jwt_secret": "too-short"},
    ],
)
def test_kakao_login_is_unavailable_when_not_configured(
    login_env, kakao_calls, monkeypatch, overrides
) -> None:
    for name, value in overrides.items():
        monkeypatch.setattr(login_env, name, value)

    with TestClient(app) as client:
        res = _login(client)

    assert res.status_code == 503
    assert res.json() == {"error": "로그인을 사용할 수 없습니다."}
    assert kakao_calls[0] == []


@pytest.mark.parametrize(
    "payload",
    [{}, {"code": "  ", "redirectUri": REDIRECT_URI}, {"code": "code-a"}],
)
def test_kakao_login_requires_code_and_redirect_uri(login_env, kakao_calls, payload) -> None:
    with TestClient(app) as client:
        res = client.post("/api/auth/kakao", json=payload)

    assert res.status_code == 400
    assert res.json() == {"error": "code와 redirectUri는 필수입니다."}
    assert kakao_calls[0] == []


def test_kakao_login_rejects_unlisted_redirect_uri(login_env, kakao_calls) -> None:
    with TestClient(app) as client:
        res = client.post(
            "/api/auth/kakao",
            json={"code": "code-a", "redirectUri": "https://evil.example/callback"},
        )

    assert res.status_code == 400
    assert res.json() == {"error": "허용되지 않은 redirectUri입니다."}
    assert kakao_calls[0] == []


@pytest.mark.parametrize(
    ("error", "status", "message"),
    [
        (kakao.KakaoAuthError("rejected"), 401, "카카오 인증에 실패했습니다."),
        (kakao.KakaoUnavailableError("down"), 502, "카카오 서버와 통신하지 못했습니다."),
    ],
)
def test_kakao_login_maps_kakao_errors(login_env, kakao_calls, error, status, message) -> None:
    _, results = kakao_calls
    results["code-a"] = error

    with TestClient(app) as client:
        res = _login(client)

    assert res.status_code == status
    assert res.json() == {"error": message}


def test_me_requires_bearer_token(login_env) -> None:
    with TestClient(app) as client:
        missing = client.get("/api/me")
        wrong_scheme = client.get("/api/me", headers={"Authorization": "Basic abc"})
        garbage = client.get("/api/me", headers=_auth("not-a-jwt"))

    for res in (missing, wrong_scheme, garbage):
        assert res.status_code == 401
        assert res.json() == {"error": "로그인이 필요합니다."}
        assert res.headers["www-authenticate"] == "Bearer"


def test_me_rejects_expired_and_foreign_tokens(login_env, kakao_calls) -> None:
    with TestClient(app) as client:
        user_id = _login(client).json()["user"]["id"]
        expired = issue_access_token(user_id, secret=SECRET, expires_in=60, now=1_000)
        foreign = issue_access_token(user_id, secret="x" * 32, expires_in=3600)

        assert client.get("/api/me", headers=_auth(expired)).status_code == 401
        assert client.get("/api/me", headers=_auth(foreign)).status_code == 401


def test_delete_me_removes_user_and_invalidates_token(login_env, kakao_calls) -> None:
    with TestClient(app) as client:
        first = _login(client).json()
        headers = _auth(first["accessToken"])

        deleted = client.delete("/api/me", headers=headers)
        assert deleted.status_code == 204
        assert deleted.content == b""

        assert client.get("/api/me", headers=headers).status_code == 401
        assert client.delete("/api/me", headers=headers).status_code == 401

        # 같은 카카오 계정으로 다시 로그인하면 새 사용자가 된다.
        again = _login(client).json()
        assert again["user"]["id"] != first["user"]["id"]
