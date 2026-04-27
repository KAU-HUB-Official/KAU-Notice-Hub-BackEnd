from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from app.classification import (
    classify_notice_audience,
    classify_notice_source_group,
    classify_notice_source_groups,
    filter_by_audience_group,
    filter_by_source_group,
    get_all_audience_groups,
    get_all_departments,
    get_all_source_groups,
    get_all_sources,
    get_clean_categories,
    normalize_filter_value,
    should_use_source_filter,
)
from app.repository import NoticeRepository
from app.schemas import Notice, NoticeFacets, NoticeListResult
from app.search import filter_notices, rank_notices


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

    def enrich_notice(self, notice: Notice) -> Notice:
        source_groups = classify_notice_source_groups(notice)
        return notice.model_copy(
            update={
                "audienceGroup": classify_notice_audience(notice),
                "sourceGroup": classify_notice_source_group(notice),
                "sourceGroups": source_groups,
            }
        )

    async def list_notices(self, query: NoticeQuery) -> NoticeListResult:
        notices = await self.repository.list_all()
        page = clamp_page(query.page)
        page_size = clamp_page_size(query.page_size)

        audience_filtered = filter_by_audience_group(notices, query.audience_group)
        source_groups = get_all_source_groups(audience_filtered)
        normalized_source_group = normalize_filter_value(query.source_group)
        effective_source_group = (
            normalized_source_group
            if normalized_source_group and normalized_source_group in source_groups
            else None
        )
        source_group_filtered = filter_by_source_group(
            audience_filtered,
            effective_source_group,
        )
        source_filter_enabled = should_use_source_filter(query.audience_group)

        facets = NoticeFacets(
            audienceGroups=get_all_audience_groups(notices),
            sourceGroups=source_groups,
            sources=(
                get_all_sources(source_group_filtered, query.audience_group, effective_source_group)
                if source_filter_enabled
                else []
            ),
            categories=get_clean_categories(source_group_filtered),
            departments=get_all_departments(source_group_filtered),
        )

        filtered = filter_notices(
            source_group_filtered,
            q=query.q,
            source=query.source if source_filter_enabled else None,
            category=normalize_filter_value(query.category),
            department=normalize_filter_value(query.department),
        )

        ranked = rank_notices(filtered, query.q)
        total = len(ranked)
        total_pages = max(1, ceil(total / page_size))
        current_page = min(page, total_pages)
        start = (current_page - 1) * page_size
        end = start + page_size

        return NoticeListResult(
            items=[self.enrich_notice(item.notice) for item in ranked[start:end]],
            total=total,
            page=current_page,
            pageSize=page_size,
            totalPages=total_pages,
            facets=facets,
        )

    async def get_notice_by_id(self, notice_id: str) -> Notice | None:
        notice = await self.repository.get_by_id(notice_id)
        return self.enrich_notice(notice) if notice else None

    async def find_relevant_notices(
        self,
        question: str,
        limit: int = 5,
        filters: NoticeQuery | None = None,
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

