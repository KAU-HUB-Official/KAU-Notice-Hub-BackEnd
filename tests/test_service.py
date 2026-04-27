import asyncio

from app.classification import DEPARTMENT_AUDIENCE_GROUP
from app.schemas import Notice
from app.service import NoticeQuery, NoticeService


class MemoryRepository:
    def __init__(self, notices: list[Notice]) -> None:
        self.notices = notices

    async def list_all(self) -> list[Notice]:
        return self.notices

    async def get_by_id(self, notice_id: str) -> Notice | None:
        return next((notice for notice in self.notices if notice.id == notice_id), None)


def make_notice(
    notice_id: str,
    title: str,
    *,
    source: str,
    category: str | None = None,
    department: str | None = None,
    date: str = "2026-04-20",
) -> Notice:
    return Notice(
        id=notice_id,
        title=title,
        content=f"{title} 본문",
        source=source,
        sources=[source],
        category=category,
        department=department,
        date=date,
        summary=f"{title} 요약",
        tags=[category, source] if category else [source],
        attachments=[],
    )


def sample_service() -> NoticeService:
    notices = [
        make_notice(
            "common-academic",
            "수강신청 안내",
            source="한국항공대학교 공식 홈페이지",
            category="학사",
            date="2026-04-20",
        ),
        make_notice(
            "common-general",
            "헌혈 행사 안내",
            source="한국항공대학교 공식 홈페이지",
            category="일반공지",
            date="2026-04-22",
        ),
        make_notice(
            "cs",
            "AI 경진대회 안내",
            source="한국항공대학교 컴퓨터공학과",
            department="컴퓨터공학과",
            date="2026-04-23",
        ),
        make_notice(
            "material-job",
            "취업 설명회",
            source="한국항공대학교 신소재공학과 취업공지",
            department="신소재공학과",
            date="2026-04-21",
        ),
        make_notice(
            "graduate",
            "대학원 학사 안내",
            source="한국항공대학교 경영대학원",
            date="2026-04-24",
        ),
    ]
    return NoticeService(MemoryRepository(notices))


def test_service_ignores_source_filter_when_audience_does_not_support_it() -> None:
    service = sample_service()

    result = asyncio.run(
        service.list_notices(
            NoticeQuery(
                audience_group="전 구성원 공통",
                source="한국항공대학교 컴퓨터공학과",
            )
        )
    )

    assert result.facets.sources == []
    assert {item.id for item in result.items} == {"common-general", "common-academic"}


def test_service_applies_source_filter_for_department_audience() -> None:
    service = sample_service()

    result = asyncio.run(
        service.list_notices(
            NoticeQuery(
                audience_group=DEPARTMENT_AUDIENCE_GROUP,
                source_group="AI융합대",
                source="한국항공대학교 컴퓨터공학과",
            )
        )
    )

    assert result.total == 1
    assert result.items[0].id == "cs"
    assert result.items[0].audienceGroup == DEPARTMENT_AUDIENCE_GROUP
    assert result.items[0].sourceGroups == ["AI융합대"]


def test_service_ignores_invalid_group_for_selected_audience() -> None:
    service = sample_service()

    result = asyncio.run(
        service.list_notices(
            NoticeQuery(
                audience_group=DEPARTMENT_AUDIENCE_GROUP,
                source_group="국제교류",
            )
        )
    )

    assert result.total == 1
    assert result.items[0].id == "cs"


def test_service_clamps_page_and_page_size() -> None:
    service = sample_service()

    result = asyncio.run(service.list_notices(NoticeQuery(page=-10, page_size=999)))

    assert result.page == 1
    assert result.pageSize == 100
    assert result.totalPages == 1


def test_service_searches_and_sorts_by_relevance() -> None:
    service = sample_service()

    result = asyncio.run(service.list_notices(NoticeQuery(q="수강신청 정보 알려줘")))

    assert result.total == 1
    assert result.items[0].id == "common-academic"

