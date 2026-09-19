"""자체 액세스 토큰(JWT) 발급·검증과 로그인 필수 의존성.

서버는 세션을 저장하지 않는다. 요청마다 토큰 서명과 만료를 검증하고, 토큰의 사용자가
DB에 아직 있는지 확인한다(탈퇴한 사용자의 토큰은 만료 전이라도 거부).

인증 실패는 원인과 상관없이 같은 401 응답을 주고, 원인은 서버 로그에만 남긴다.
"""

from __future__ import annotations

import asyncio
import logging
import time

import jwt
from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import user_store
from app.config import Settings, get_settings
from app.user_store import UserRecord

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
# HS256 키가 짧으면 무차별 대입으로 서명을 위조할 수 있어 32자 미만은 미설정으로 본다.
MIN_JWT_SECRET_LENGTH = 32


class AuthenticationRequired(Exception):
    """로그인이 필요하거나 토큰이 유효하지 않다."""


def jwt_secret(settings: Settings) -> str | None:
    secret = settings.jwt_secret
    if secret and len(secret) >= MIN_JWT_SECRET_LENGTH:
        return secret
    return None


def issue_access_token(
    user_id: str, *, secret: str, expires_in: int, now: int | None = None
) -> str:
    issued_at = int(time.time()) if now is None else now
    claims = {"sub": user_id, "iat": issued_at, "exp": issued_at + expires_in}
    return jwt.encode(claims, secret, algorithm=JWT_ALGORITHM)


def decode_user_id(token: str, *, secret: str) -> str | None:
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "iat", "exp"]},
        )
    except jwt.ExpiredSignatureError:
        logger.info("auth: expired access token")
        return None
    except jwt.InvalidTokenError as exc:
        logger.info("auth: invalid access token (%s)", type(exc).__name__)
        return None
    subject = claims.get("sub")
    return subject if isinstance(subject, str) and subject else None


# OpenAPI에 Bearer 인증을 선언해 /docs에 Authorize 버튼이 생기게 한다.
# auto_error=False: 토큰이 없을 때 FastAPI 기본 응답({"detail": ...}) 대신
# 아래 get_current_user가 기존 ErrorResponse 형식의 401을 돌려주게 한다.
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> UserRecord:
    """로그인이 필요한 엔드포인트의 의존성. 실패하면 AuthenticationRequired를 던진다."""
    settings = get_settings()
    token = credentials.credentials.strip() if credentials else None
    secret = jwt_secret(settings)
    if not token or not secret:
        raise AuthenticationRequired()

    user_id = decode_user_id(token, secret=secret)
    if not user_id:
        raise AuthenticationRequired()

    user = await asyncio.to_thread(user_store.get_user, settings.user_db_path, user_id)
    if user is None:
        logger.info("auth: token for missing user")
        raise AuthenticationRequired()
    return user


def authentication_required_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"error": "로그인이 필요합니다."},
        headers={"WWW-Authenticate": "Bearer"},
    )


def user_store_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """의존성(get_current_user)에서 사용자 DB 조회가 실패한 경우의 일반화 응답."""
    logger.error("auth: user store failure", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"error": "사용자 정보를 확인하지 못했습니다."},
    )
