"""In-memory search pipeline used as a fallback when SQLite is unavailable."""

from __future__ import annotations

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
from app.repository import NoticeSearchQuery, NoticeSearchResult
from app.schemas import Notice, NoticeFacets
from app.search import filter_notices, rank_notices


def _enrich(notice: Notice) -> Notice:
    return notice.model_copy(
        update={
            "audienceGroup": classify_notice_audience(notice),
            "sourceGroup": classify_notice_source_group(notice),
            "sourceGroups": classify_notice_source_groups(notice),
        }
    )


def legacy_search(notices: list[Notice], query: NoticeSearchQuery) -> NoticeSearchResult:
    audience_filtered = filter_by_audience_group(notices, query.audience_group)
    source_groups = get_all_source_groups(audience_filtered)
    normalized_source_group = normalize_filter_value(query.source_group)
    effective_source_group = (
        normalized_source_group
        if normalized_source_group and normalized_source_group in source_groups
        else None
    )
    source_group_filtered = filter_by_source_group(audience_filtered, effective_source_group)
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
    page_size = max(1, query.page_size)
    total_pages = max(1, ceil(total / page_size))
    current_page = min(max(1, query.page), total_pages)
    start = (current_page - 1) * page_size
    end = start + page_size

    items = [_enrich(item.notice) for item in ranked[start:end]]
    return NoticeSearchResult(
        items=items,
        total=total,
        facets=facets,
        effective_source_group=effective_source_group,
    )
