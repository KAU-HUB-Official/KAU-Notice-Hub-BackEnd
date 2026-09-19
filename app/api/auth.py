import asyncio
import logging

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from app import kakao, user_store
from app.auth import get_current_user, issue_access_token, jwt_secret
from app.config import get_settings
from app.rate_limit import auth_rate_limit, bookmarks_rate_limit, limiter
from app.schemas import AuthResult, ErrorResponse, KakaoLoginRequest, User
from app.user_store import UserRecord, UserStoreError


router = APIRouter(tags=["auth"])
logger = logging.getLogger(__name__)


def _to_user(record: UserRecord) -> User:
    return User(id=record.id, nickname=record.nickname)


@router.post(
    "/api/auth/kakao",
    response_model=AuthResult,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
@limiter.shared_limit(auth_rate_limit, scope="auth")
async def login_with_kakao(
    request: Request, body: KakaoLoginRequest
) -> AuthResult | JSONResponse:
    settings = get_settings()
    secret = jwt_secret(settings)
    allowed_redirect_uris = settings.kakao_allowed_redirect_uri_list
    if not settings.kakao_rest_api_key or not allowed_redirect_uris or not secret:
        logger.warning(
            "kakao login is not configured: rest_api_key=%s redirect_uris=%s jwt_secret=%s",
            bool(settings.kakao_rest_api_key),
            bool(allowed_redirect_uris),
            bool(secret),
        )
        return JSONResponse(
            status_code=503, content={"error": "로그인을 사용할 수 없습니다."}
        )

    code = (body.code or "").strip()
    redirect_uri = (body.redirectUri or "").strip()
    if not code or not redirect_uri:
        return JSONResponse(
            status_code=400, content={"error": "code와 redirectUri는 필수입니다."}
        )
    if redirect_uri not in allowed_redirect_uris:
        logger.warning("kakao login with disallowed redirect_uri")
        return JSONResponse(
            status_code=400, content={"error": "허용되지 않은 redirectUri입니다."}
        )

    try:
        profile = await asyncio.to_thread(
            kakao.fetch_profile_by_code,
            code,
            redirect_uri,
            client_id=settings.kakao_rest_api_key,
            client_secret=settings.kakao_client_secret,
        )
    except kakao.KakaoAuthError:
        return JSONResponse(
            status_code=401, content={"error": "카카오 인증에 실패했습니다."}
        )
    except kakao.KakaoUnavailableError:
        return JSONResponse(
            status_code=502, content={"error": "카카오 서버와 통신하지 못했습니다."}
        )

    try:
        user = await asyncio.to_thread(
            user_store.upsert_kakao_user,
            settings.user_db_path,
            kakao_id=profile.kakao_id,
            nickname=profile.nickname,
        )
    except UserStoreError:
        logger.exception("Failed to save kakao user")
        return JSONResponse(
            status_code=500, content={"error": "로그인을 처리하지 못했습니다."}
        )

    return AuthResult(
        accessToken=issue_access_token(
            user.id, secret=secret, expires_in=settings.jwt_expire_seconds
        ),
        expiresIn=settings.jwt_expire_seconds,
        user=_to_user(user),
    )


@router.get(
    "/api/me",
    response_model=User,
    responses={
        401: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
@limiter.shared_limit(bookmarks_rate_limit, scope="bookmarks")
async def read_me(
    request: Request, user: UserRecord = Depends(get_current_user)
) -> User:
    return _to_user(user)


@router.delete(
    "/api/me",
    status_code=204,
    response_class=Response,
    responses={
        401: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
@limiter.shared_limit(bookmarks_rate_limit, scope="bookmarks")
async def delete_me(
    request: Request, user: UserRecord = Depends(get_current_user)
) -> Response:
    try:
        await asyncio.to_thread(
            user_store.delete_user, get_settings().user_db_path, user.id
        )
    except UserStoreError:
        logger.exception("Failed to delete user")
        return JSONResponse(
            status_code=500, content={"error": "회원 탈퇴를 처리하지 못했습니다."}
        )
    return Response(status_code=204)
