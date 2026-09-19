import pytest
import requests

from app import kakao


class _FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


@pytest.fixture()
def fake_http(monkeypatch):
    """requests.post(토큰 교환)와 requests.get(사용자 정보)을 가짜 응답으로 바꾼다."""
    state: dict = {
        "token": _FakeResponse(200, {"access_token": "kakao-access-token"}),
        "user": _FakeResponse(
            200,
            {
                "id": 1001,
                "kakao_account": {
                    "profile": {
                        "nickname": "항공대생",
                        # 동의항목에 없어도 카카오가 보낼 수 있다. 저장하지 않는다.
                        "profile_image_url": "https://k.kakaocdn.net/a.jpg",
                    }
                },
            },
        ),
        "calls": [],
    }

    def respond(key: str, url: str, kwargs: dict):
        state["calls"].append((key, url, kwargs))
        result = state[key]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(
        kakao.requests, "post", lambda url, **kwargs: respond("token", url, kwargs)
    )
    monkeypatch.setattr(
        kakao.requests, "get", lambda url, **kwargs: respond("user", url, kwargs)
    )
    return state


def _fetch(**kwargs) -> kakao.KakaoProfile:
    return kakao.fetch_profile_by_code(
        "auth-code", "http://localhost:3000/auth/kakao/callback", client_id="rest-key", **kwargs
    )


def test_fetch_profile_exchanges_code_then_reads_user(fake_http) -> None:
    profile = _fetch(client_secret="client-secret")

    assert profile == kakao.KakaoProfile("1001", "항공대생")

    (token_call, user_call) = fake_http["calls"]
    assert token_call[1] == kakao.KAKAO_TOKEN_URL
    assert token_call[2]["data"] == {
        "grant_type": "authorization_code",
        "client_id": "rest-key",
        "redirect_uri": "http://localhost:3000/auth/kakao/callback",
        "code": "auth-code",
        "client_secret": "client-secret",
    }
    assert token_call[2]["timeout"] == kakao.REQUEST_TIMEOUT_SECONDS
    assert user_call[1] == kakao.KAKAO_USER_URL
    assert user_call[2]["headers"] == {"Authorization": "Bearer kakao-access-token"}


def test_fetch_profile_omits_client_secret_when_not_set(fake_http) -> None:
    _fetch()

    assert "client_secret" not in fake_http["calls"][0][2]["data"]


def test_fetch_profile_allows_missing_optional_profile(fake_http) -> None:
    fake_http["user"] = _FakeResponse(200, {"id": 1001, "kakao_account": {}})

    assert _fetch() == kakao.KakaoProfile("1001", None)


def test_rejected_code_raises_auth_error(fake_http) -> None:
    fake_http["token"] = _FakeResponse(
        400, {"error": "invalid_grant", "error_code": "KOE320"}
    )

    with pytest.raises(kakao.KakaoAuthError):
        _fetch()
    assert len(fake_http["calls"]) == 1


@pytest.mark.parametrize(
    "token_result",
    [
        requests.ConnectionError("boom"),
        requests.Timeout("slow"),
        _FakeResponse(503, {"msg": "maintenance"}),
        _FakeResponse(200, ValueError("not json")),
        _FakeResponse(200, {"token_type": "bearer"}),
    ],
)
def test_unreachable_or_malformed_token_response_raises_unavailable(
    fake_http, token_result
) -> None:
    fake_http["token"] = token_result

    with pytest.raises(kakao.KakaoUnavailableError):
        _fetch()


def test_user_response_without_id_raises_unavailable(fake_http) -> None:
    fake_http["user"] = _FakeResponse(200, {"kakao_account": {}})

    with pytest.raises(kakao.KakaoUnavailableError):
        _fetch()
