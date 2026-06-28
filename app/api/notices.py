import logging

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.dependencies import get_notice_service
from app.rate_limit import limiter, notices_rate_limit
from app.repository import NoticeRepositoryError
from app.schemas import ErrorResponse, Notice, NoticeListResult
from app.service import NoticeQuery, NoticeService


router = APIRouter(prefix="/api/notices", tags=["notices"])
logger = logging.getLogger(__name__)


def parse_number(value: str | None, fallback: int) -> int:
    if value is None:
        return fallback

    try:
        return int(value)
    except ValueError:
        return fallback


@router.get(
    "",
    response_model=NoticeListResult,
    responses={429: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
@limiter.shared_limit(notices_rate_limit, scope="notices")
async def list_notices(
    request: Request,
    q: str | None = None,
    audience: str | None = None,
    group: str | None = None,
    sourceGroup: str | None = None,
    source: str | None = None,
    category: str | None = None,
    department: str | None = None,
    page: str | None = Query(default=None),
    pageSize: str | None = Query(default=None),
    service: NoticeService = Depends(get_notice_service),
) -> NoticeListResult | JSONResponse:
    try:
        return await service.list_notices(
            NoticeQuery(
                q=q,
                audience_group=audience,
                source_group=group or sourceGroup,
                source=source,
                category=category,
                department=department,
                page=parse_number(page, 1),
                page_size=parse_number(pageSize, 20),
            )
        )
    except NoticeRepositoryError:
        logger.exception("Failed to load notice list")
        return JSONResponse(
            status_code=500,
            content={"error": "공지 목록을 불러오지 못했습니다."},
        )


@router.get(
    "/{notice_id}",
    response_model=Notice,
    responses={
        404: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
@limiter.shared_limit(notices_rate_limit, scope="notices")
async def get_notice(
    request: Request,
    notice_id: str,
    service: NoticeService = Depends(get_notice_service),
) -> Notice | JSONResponse:
    try:
        notice = await service.get_notice_by_id(notice_id)
    except NoticeRepositoryError:
        logger.exception("Failed to load notice detail: %s", notice_id)
        return JSONResponse(
            status_code=500,
            content={"error": "공지 상세를 불러오지 못했습니다."},
        )

    if not notice:
        return JSONResponse(status_code=404, content={"error": "공지 항목을 찾을 수 없습니다."})

    return notice
