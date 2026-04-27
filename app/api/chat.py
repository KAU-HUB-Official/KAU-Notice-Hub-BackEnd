from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.chat_service import ask_notice_question
from app.dependencies import get_notice_service
from app.repository import NoticeRepositoryError
from app.schemas import ChatAnswer, ChatRequestBody, ErrorResponse
from app.service import NoticeQuery, NoticeService


router = APIRouter(prefix="/api/chat", tags=["chat"])


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
    if not question:
        return JSONResponse(status_code=400, content={"error": "question 필드는 필수입니다."})

    if len(question) > 500:
        return JSONResponse(status_code=400, content={"error": "질문은 500자 이하로 입력해주세요."})

    try:
        return await ask_notice_question(
            service,
            question,
            NoticeQuery(
                audience_group=body.audienceGroup,
                source_group=body.sourceGroup,
                source=body.source,
                category=body.category,
                department=body.department,
            ),
        )
    except NoticeRepositoryError as exc:
        return JSONResponse(
            status_code=500,
            content={"error": "챗봇 응답을 생성하지 못했습니다.", "detail": str(exc)},
        )
