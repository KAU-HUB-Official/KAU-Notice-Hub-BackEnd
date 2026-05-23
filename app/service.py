from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from app.classification import (
    classify_notice_audience,
    classify_notice_source_group,
    classify_notice_source_groups,
)
from app.repository import NoticeRepository, NoticeSearchQuery
from app.schemas import Notice, NoticeListResult


@dataclass(frozen=True)
class NoticeQuery:
    q: str | None = None
    audience_group: str | None = None
    source_group: str | None = None
    source: str | None = None
    category: str | None = None
    department: str | None = None
    page: int | None = None
    page_size: int | None = None


def clamp_page(value: int | None = None) -> int:
    if not value or value < 1:
        return 1
    return int(value)


def clamp_page_size(value: int | None = None) -> int:
    if not value:
        return 20

    size = int(value)
    if size < 1:
        return 1
    if size > 100:
        return 100
    return size


class NoticeService:
    def __init__(self, repository: NoticeRepository) -> None:
        self.repository = repository

    async def list_notices(self, query: NoticeQuery) -> NoticeListResult:
        page = clamp_page(query.page)
        page_size = clamp_page_size(query.page_size)
        result = await self.repository.search(
            NoticeSearchQuery(
                q=query.q,
                audience_group=query.audience_group,
                source_group=query.source_group,
                source=query.source,
                category=query.category,
                department=query.department,
                page=page,
                page_size=page_size,
            )
        )
        total_pages = max(1, ceil(result.total / page_size))
        current_page = min(page, total_pages)

        return NoticeListResult(
            items=result.items,
            total=result.total,
            page=current_page,
            pageSize=page_size,
            totalPages=total_pages,
            facets=result.facets,
        )

    async def get_notice_by_id(self, notice_id: str) -> Notice | None:
        notice = await self.repository.get_by_id(notice_id)
        if notice is None or notice.audienceGroup is not None:
            return notice
        return notice.model_copy(
            update={
                "audienceGroup": classify_notice_audience(notice),
                "sourceGroup": classify_notice_source_group(notice),
                "sourceGroups": classify_notice_source_groups(notice),
            }
        )

    async def find_relevant_notices(
        self,
        question: str,
        limit: int = 5,
        filters: NoticeQuery | None = None,
        fallback_to_latest: bool = True,
    ) -> list[Notice]:
        base = filters or NoticeQuery()
        search = await self.list_notices(
            NoticeQuery(
                q=question,
                audience_group=base.audience_group,
                source_group=base.source_group,
                source=base.source,
                category=base.category,
                department=base.department,
                page=1,
                page_size=limit,
            )
        )
        if search.items:
            return search.items

        if not fallback_to_latest:
            return []

        latest = await self.list_notices(
            NoticeQuery(
                audience_group=base.audience_group,
                source_group=base.source_group,
                source=base.source,
                category=base.category,
                department=base.department,
                page=1,
                page_size=limit,
            )
        )
        return latest.items
