import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse

from app.chat_service import ask_notice_question, stream_notice_question
from app.dependencies import get_notice_service
from app.repository import NoticeRepositoryError
from app.schemas import ChatAnswer, ChatRequestBody, ErrorResponse
from app.service import NoticeQuery, NoticeService


router = APIRouter(prefix="/api/chat", tags=["chat"])
logger = logging.getLogger(__name__)


def _validate_question(question: str) -> JSONResponse | None:
    if not question:
        return JSONResponse(status_code=400, content={"error": "question 필드는 필수입니다."})
    if len(question) > 500:
        return JSONResponse(status_code=400, content={"error": "질문은 500자 이하로 입력해주세요."})
    return None


def _query_from_body(body: ChatRequestBody) -> NoticeQuery:
    return NoticeQuery(
        audience_group=body.audienceGroup,
        source_group=body.sourceGroup,
        source=body.source,
        category=body.category,
        department=body.department,
    )


@router.post(
    "",
    response_model=ChatAnswer,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def chat(
    body: ChatRequestBody,
    service: NoticeService = Depends(get_notice_service),
) -> ChatAnswer | JSONResponse:
    question = (body.question or "").strip()
    error = _validate_question(question)
    if error is not None:
        return error

    try:
        return await ask_notice_question(service, question, _query_from_body(body))
    except NoticeRepositoryError:
        logger.exception("Failed to create chat response")
        return JSONResponse(
            status_code=500,
            content={"error": "챗봇 응답을 생성하지 못했습니다."},
        )


@router.post(
    "/stream",
    response_model=None,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def chat_stream(
    body: ChatRequestBody,
    service: NoticeService = Depends(get_notice_service),
) -> StreamingResponse | JSONResponse:
    question = (body.question or "").strip()
    error = _validate_question(question)
    if error is not None:
        return error

    filters = _query_from_body(body)

    async def event_source():
        try:
            async for event in stream_notice_question(service, question, filters):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except NoticeRepositoryError:
            logger.exception("Failed to stream chat response")
            yield (
                "event: error\n"
                "data: "
                + json.dumps(
                    {"type": "error", "error": "챗봇 응답을 생성하지 못했습니다."},
                    ensure_ascii=False,
                )
                + "\n\n"
            )

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
