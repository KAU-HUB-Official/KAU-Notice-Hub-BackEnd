"""카카오 로그인 REST API 호출.

프론트가 받은 인가 code를 카카오 토큰으로 교환하고, 그 토큰으로 사용자 정보를
조회한다. 카카오 access token은 사용자 확인에만 쓰고 저장하지 않는다.

오류는 두 가지로만 나눈다.
- KakaoAuthError: 카카오가 요청을 거부함(code 만료·재사용·위조, redirect_uri 불일치 등)
- KakaoUnavailableError: 카카오와 통신할 수 없거나 응답이 예상과 다름

카카오가 돌려준 오류 코드는 서버 로그에만 남기고 API 응답에는 넣지 않는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)

KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_USER_URL = "https://kapi.kakao.com/v2/user/me"
REQUEST_TIMEOUT_SECONDS = 5


class KakaoAuthError(Exception):
    """카카오가 인가 code 또는 토큰을 거부했다."""


class KakaoUnavailableError(Exception):
    """카카오 API 타임아웃·5xx·예상과 다른 응답."""


@dataclass(frozen=True)
class KakaoProfile:
    kakao_id: str
    nickname: str | None


def fetch_profile_by_code(
    code: str,
    redirect_uri: str,
    *,
    client_id: str,
    client_secret: str | None = None,
) -> KakaoProfile:
    access_token = _exchange_code(
        code, redirect_uri, client_id=client_id, client_secret=client_secret
    )
    return _fetch_profile(access_token)


def _exchange_code(
    code: str, redirect_uri: str, *, client_id: str, client_secret: str | None
) -> str:
    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code": code,
    }
    if client_secret:
        data["client_secret"] = client_secret

    payload = _call("token", requests.post, KAKAO_TOKEN_URL, data=data)
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        logger.error("kakao token response has no access_token")
        raise KakaoUnavailableError("카카오 토큰 응답이 올바르지 않습니다.")
    return access_token


def _fetch_profile(access_token: str) -> KakaoProfile:
    payload = _call(
        "user",
        requests.get,
        KAKAO_USER_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    kakao_id = payload.get("id")
    if not isinstance(kakao_id, int):
        logger.error("kakao user response has no id")
        raise KakaoUnavailableError("카카오 사용자 응답이 올바르지 않습니다.")

    account = payload.get("kakao_account")
    profile = account.get("profile") if isinstance(account, dict) else None
    if not isinstance(profile, dict):
        profile = {}
    return KakaoProfile(
        kakao_id=str(kakao_id),
        nickname=_optional_string(profile.get("nickname")),
    )


def _call(step: str, method: Any, url: str, **kwargs: Any) -> dict[str, Any]:
    try:
        response = method(url, timeout=REQUEST_TIMEOUT_SECONDS, **kwargs)
    except requests.RequestException as exc:
        logger.warning("kakao %s request failed: %s", step, type(exc).__name__)
        raise KakaoUnavailableError("카카오 서버와 통신하지 못했습니다.") from exc

    if response.status_code >= 500:
        logger.warning("kakao %s request returned %s", step, response.status_code)
        raise KakaoUnavailableError("카카오 서버와 통신하지 못했습니다.")

    try:
        payload = response.json()
    except ValueError as exc:
        logger.error("kakao %s response is not JSON (status=%s)", step, response.status_code)
        raise KakaoUnavailableError("카카오 응답이 올바르지 않습니다.") from exc
    if not isinstance(payload, dict):
        logger.error("kakao %s response is not an object", step)
        raise KakaoUnavailableError("카카오 응답이 올바르지 않습니다.")

    if response.status_code >= 400:
        # KOE320(code 만료·재사용), KOE006(redirect_uri 미등록), KOE101(잘못된 앱 키) 등.
        # 앱 키 오류는 서버 설정 문제이므로 로그로 구분할 수 있게 코드를 남긴다.
        logger.warning(
            "kakao %s request rejected: status=%s error=%s error_code=%s",
            step,
            response.status_code,
            payload.get("error"),
            payload.get("error_code") or payload.get("code"),
        )
        raise KakaoAuthError("카카오 인증에 실패했습니다.")
    return payload


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
