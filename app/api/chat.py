import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app import chat_log
from app.chat_service import ask_notice_question, stream_notice_question
from app.config import get_settings
from app.dependencies import get_notice_service
from app.rate_limit import chat_rate_limit, limiter
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


def _filters_dict(body: ChatRequestBody) -> dict[str, str | None]:
    return {
        "audience_group": body.audienceGroup,
        "source_group": body.sourceGroup,
        "source": body.source,
        "category": body.category,
        "department": body.department,
    }


def _session_logging(body: ChatRequestBody) -> str | None:
    """로깅이 켜져 있고 sessionId가 있으면 chat_log_db_path(str)를, 아니면 None."""
    settings = get_settings()
    if settings.chat_logging_enabled and body.sessionId:
        return str(settings.chat_log_db_path)
    return None


@router.post(
    "",
    response_model=ChatAnswer,
    responses={
        400: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
@limiter.shared_limit(chat_rate_limit, scope="chat")
async def chat(
    request: Request,
    body: ChatRequestBody,
    background_tasks: BackgroundTasks,
    service: NoticeService = Depends(get_notice_service),
) -> ChatAnswer | JSONResponse:
    question = (body.question or "").strip()
    error = _validate_question(question)
    if error is not None:
        return error

    # 저장은 응답 전송 후 백그라운드에서 실행해 응답 지연을 만들지 않는다.
    # 사용자 입력은 답변 생성 실패와 무관하게 남도록 먼저 예약한다.
    log_db = _session_logging(body)
    if log_db:
        background_tasks.add_task(
            chat_log.record_user_message,
            log_db,
            body.sessionId,
            question,
            filters=_filters_dict(body),
        )

    try:
        answer = await ask_notice_question(
            service, question, _query_from_body(body), body.history
        )
    except NoticeRepositoryError:
        logger.exception("Failed to create chat response")
        return JSONResponse(
            status_code=500,
            content={"error": "챗봇 응답을 생성하지 못했습니다."},
        )

    if log_db:
        background_tasks.add_task(
            chat_log.record_assistant_message,
            log_db,
            body.sessionId,
            answer.answer,
            references=[ref.model_dump() for ref in answer.references],
            used_fallback=answer.usedFallback,
            model=answer.model,
        )
    return answer


@router.post(
    "/stream",
    response_model=None,
    responses={
        400: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
@limiter.shared_limit(chat_rate_limit, scope="chat")
async def chat_stream(
    request: Request,
    body: ChatRequestBody,
    service: NoticeService = Depends(get_notice_service),
) -> StreamingResponse | JSONResponse:
    question = (body.question or "").strip()
    error = _validate_question(question)
    if error is not None:
        return error

    filters = _query_from_body(body)
    history = list(body.history)
    log_db = _session_logging(body)

    async def event_source():
        if log_db:
            chat_log.fire_and_forget(
                chat_log.record_user_message,
                log_db,
                body.sessionId,
                question,
                filters=_filters_dict(body),
            )

        # 스트림 이벤트를 흘려보내며 최종 답변/references를 함께 모은다.
        references: list[dict] = []
        answer: str | None = None
        used_fallback = True
        model: str | None = None
        try:
            async for event in stream_notice_question(service, question, filters, history):
                event_type = event.get("type")
                if event_type == "search_completed":
                    references = event.get("references", [])
                elif event_type == "answer_completed":
                    answer = event.get("answer")
                    used_fallback = event.get("usedFallback", True)
                    model = event.get("model")
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

        # 토큰 전송이 끝난 뒤 백그라운드로 답변 턴을 저장한다(전송 비차단).
        if log_db and answer is not None:
            chat_log.fire_and_forget(
                chat_log.record_assistant_message,
                log_db,
                body.sessionId,
                answer,
                references=references,
                used_fallback=used_fallback,
                model=model,
            )

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
