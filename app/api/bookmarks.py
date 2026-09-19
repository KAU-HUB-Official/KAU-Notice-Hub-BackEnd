import asyncio
import logging
from math import ceil

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from app import user_store
from app.api.notices import parse_number
from app.auth import get_current_user
from app.config import get_settings
from app.dependencies import get_notice_service
from app.rate_limit import bookmarks_rate_limit, limiter
from app.repository import NoticeRepositoryError
from app.schemas import (
    Bookmark,
    BookmarkIdsResult,
    BookmarkListResult,
    ErrorResponse,
    Notice,
    NoticeReference,
)
from app.service import NoticeService, clamp_page, clamp_page_size
from app.user_store import (
    BookmarkLimitExceeded,
    BookmarkRecord,
    UserRecord,
    UserStoreError,
)


router = APIRouter(prefix="/api/bookmarks", tags=["bookmarks"])
logger = logging.getLogger(__name__)

_AUTH_ERRORS = {
    401: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}


def _to_bookmark(record: BookmarkRecord, notice: Notice | None) -> Bookmark:
    return Bookmark(
        noticeId=record.notice_id,
        bookmarkedAt=record.bookmarked_at,
        notice=notice,
        saved=NoticeReference(
            id=record.notice_id,
            title=record.title,
            url=record.url,
            source=record.source,
            date=record.date,
        ),
    )


@router.get("", response_model=BookmarkListResult, responses=_AUTH_ERRORS)
@limiter.shared_limit(bookmarks_rate_limit, scope="bookmarks")
async def list_bookmarks(
    request: Request,
    page: str | None = Query(default=None),
    pageSize: str | None = Query(default=None),
    user: UserRecord = Depends(get_current_user),
    service: NoticeService = Depends(get_notice_service),
) -> BookmarkListResult | JSONResponse:
    page_size = clamp_page_size(parse_number(pageSize, 20))

    try:
        records, total, current_page = await asyncio.to_thread(
            user_store.list_bookmarks,
            get_settings().user_db_path,
            user.id,
            page=clamp_page(parse_number(page, 1)),
            page_size=page_size,
        )
        # 공지가 1년이 지나 스냅샷에서 빠졌으면 None이 되고 saved 사본만 남는다.
        notices = await asyncio.gather(
            *(service.get_notice_by_id(record.notice_id) for record in records)
        )
    except (UserStoreError, NoticeRepositoryError):
        logger.exception("Failed to list bookmarks")
        return JSONResponse(
            status_code=500, content={"error": "북마크 목록을 불러오지 못했습니다."}
        )

    return BookmarkListResult(
        items=[_to_bookmark(record, notice) for record, notice in zip(records, notices)],
        total=total,
        page=current_page,
        pageSize=page_size,
        totalPages=max(1, ceil(total / page_size)),
    )


@router.get("/ids", response_model=BookmarkIdsResult, responses=_AUTH_ERRORS)
@limiter.shared_limit(bookmarks_rate_limit, scope="bookmarks")
async def list_bookmark_ids(
    request: Request, user: UserRecord = Depends(get_current_user)
) -> BookmarkIdsResult | JSONResponse:
    try:
        notice_ids = await asyncio.to_thread(
            user_store.list_bookmark_ids, get_settings().user_db_path, user.id
        )
    except UserStoreError:
        logger.exception("Failed to list bookmark ids")
        return JSONResponse(
            status_code=500, content={"error": "북마크 목록을 불러오지 못했습니다."}
        )
    return BookmarkIdsResult(noticeIds=notice_ids)


@router.put(
    "/{notice_id}",
    response_model=Bookmark,
    status_code=200,
    responses={
        201: {"model": Bookmark},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        **_AUTH_ERRORS,
    },
)
@limiter.shared_limit(bookmarks_rate_limit, scope="bookmarks")
async def add_bookmark(
    request: Request,
    response: Response,
    notice_id: str,
    user: UserRecord = Depends(get_current_user),
    service: NoticeService = Depends(get_notice_service),
) -> Bookmark | JSONResponse:
    settings = get_settings()
    try:
        existing = await asyncio.to_thread(
            user_store.get_bookmark, settings.user_db_path, user.id, notice_id
        )
        notice = await service.get_notice_by_id(notice_id)
        # 이미 북마크한 공지는 스냅샷에서 빠졌어도 그대로 돌려준다(멱등).
        if existing:
            return _to_bookmark(existing, notice)
        if notice is None:
            return JSONResponse(
                status_code=404, content={"error": "공지 항목을 찾을 수 없습니다."}
            )

        record, created = await asyncio.to_thread(
            user_store.add_bookmark,
            settings.user_db_path,
            user.id,
            notice_id=notice.id,
            title=notice.title,
            url=notice.url,
            source=notice.source,
            date=notice.date,
            max_count=settings.bookmark_max_per_user,
        )
    except BookmarkLimitExceeded:
        return JSONResponse(
            status_code=409,
            content={
                "error": f"북마크는 최대 {settings.bookmark_max_per_user}개까지 저장할 수 있습니다."
            },
        )
    except (UserStoreError, NoticeRepositoryError):
        logger.exception("Failed to add bookmark")
        return JSONResponse(
            status_code=500, content={"error": "북마크를 저장하지 못했습니다."}
        )

    if created:
        response.status_code = 201
    return _to_bookmark(record, notice)


@router.delete(
    "/{notice_id}",
    status_code=204,
    response_class=Response,
    responses=_AUTH_ERRORS,
)
@limiter.shared_limit(bookmarks_rate_limit, scope="bookmarks")
async def delete_bookmark(
    request: Request,
    notice_id: str,
    user: UserRecord = Depends(get_current_user),
) -> Response:
    try:
        await asyncio.to_thread(
            user_store.remove_bookmark, get_settings().user_db_path, user.id, notice_id
        )
    except UserStoreError:
        logger.exception("Failed to delete bookmark")
        return JSONResponse(
            status_code=500, content={"error": "북마크를 삭제하지 못했습니다."}
        )
    return Response(status_code=204)
