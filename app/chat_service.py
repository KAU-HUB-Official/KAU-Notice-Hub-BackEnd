from app.classification import get_notice_source_names
from app.schemas import ChatAnswer, Notice, NoticeReference
from app.service import NoticeQuery, NoticeService


def truncate(input_value: str, max_length: int) -> str:
    if len(input_value) <= max_length:
        return input_value
    return f"{input_value[:max_length]}..."


def build_references(notices: list[Notice]) -> list[NoticeReference]:
    return [
        NoticeReference(
            id=notice.id,
            title=notice.title,
            url=notice.url,
            source=notice.source,
            date=notice.date,
        )
        for notice in notices
    ]


def build_context(notices: list[Notice]) -> str:
    if not notices:
        return "관련 공지를 찾지 못했습니다."

    blocks: list[str] = []
    for index, notice in enumerate(notices, start=1):
        blocks.append(
            "\n".join(
                [
                    f"공지 {index}",
                    f"id: {notice.id}",
                    f"title: {notice.title}",
                    f"date: {notice.date or '날짜 미상'}",
                    f"audience: {notice.audienceGroup or '대상 미분류'}",
                    f"source_group: {notice.sourceGroup or '중분류 없음'}",
                    f"sources: {', '.join(get_notice_source_names(notice)) or '출처 미상'}",
                    f"category: {notice.category or '분류 없음'}",
                    f"url: {notice.url or '링크 없음'}",
                    f"summary: {notice.summary or '요약 없음'}",
                    f"content: {truncate(notice.content, 1400)}",
                ]
            )
        )
    return "\n\n".join(blocks)


def fallback_answer(question: str, notices: list[Notice]) -> str:
    if not notices:
        return "관련 공지를 찾지 못했습니다. 검색어를 더 구체적으로 입력하거나 공지 목록에서 직접 확인해주세요."

    lines: list[str] = []
    for index, notice in enumerate(notices[:3], start=1):
        meta = " | ".join(value for value in [notice.date, notice.source] if value)
        summary = notice.summary or "요약 정보 없음"
        lines.append(f"{index}. {notice.title}\n{meta}\n{summary}")

    return "\n".join(
        [
            f"질문: {question}",
            "",
            "OpenAI API 키가 없어 로컬 검색 결과를 기준으로 안내합니다.",
            "",
            *lines,
            "",
            "정확한 일정/세부조건은 각 공지 원문 링크에서 확인해주세요.",
        ]
    )


async def ask_notice_question(
    service: NoticeService,
    question: str,
    filters: NoticeQuery | None = None,
) -> ChatAnswer:
    normalized_question = question.strip()
    references_source = await service.find_relevant_notices(
        normalized_question,
        limit=6,
        filters=filters,
    )
    references = build_references(references_source)

    return ChatAnswer(
        answer=fallback_answer(normalized_question, references_source),
        references=references,
        usedFallback=True,
        model="local-fallback",
    )

