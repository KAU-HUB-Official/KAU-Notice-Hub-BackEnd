from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re

from app.classification import (
    classify_notice_audience,
    classify_notice_source_groups,
    compact,
    get_notice_source_names,
    normalize_facet_value,
    normalize_filter_value,
    normalize_whitespace,
)
from app.schemas import Notice


SEARCH_STOP_WORDS = {
    "공지",
    "공지사항",
    "정보",
    "내용",
    "관련",
    "문의",
    "질문",
    "알려줘",
    "알려주세요",
    "보여줘",
    "보여주세요",
    "뭐야",
    "무엇",
    "뭔지",
    "정리",
    "요약",
    "최신",
    "최근",
    "확인",
    "안내",
    "좀",
    "해줘",
    "해주세요",
    "please",
    "show",
    "find",
    "about",
    "latest",
    "info",
}


@dataclass(frozen=True)
class RankedNotice:
    notice: Notice
    score: int


def extract_search_terms(input_value: str | None = None) -> list[str]:
    normalized_input = normalize_whitespace(input_value or "")
    if not normalized_input:
        return []

    raw_tokens = [
        token.strip()
        for token in re.split(r"[^\w]+", normalized_input.lower(), flags=re.UNICODE)
        if token.strip()
    ]
    if not raw_tokens:
        return []

    significant = [
        token
        for token in raw_tokens
        if token not in SEARCH_STOP_WORDS and not (len(token) == 1 and not token.isdigit())
    ]
    selected = significant if significant else raw_tokens

    seen: set[str] = set()
    terms: list[str] = []
    for token in selected:
        if token in seen:
            continue
        seen.add(token)
        terms.append(token)
    return terms


def build_search_text(notice: Notice) -> str:
    values = [
        notice.title,
        notice.summary,
        notice.content,
        classify_notice_audience(notice),
        *classify_notice_source_groups(notice),
        normalize_facet_value(notice.source),
        normalize_facet_value(notice.department),
        normalize_facet_value(notice.category),
        *get_notice_source_names(notice),
        *notice.tags,
    ]
    return "\n".join(value for value in values if value).lower()


def score_notice(notice: Notice, terms: list[str]) -> int:
    if not terms:
        return 0

    title = notice.title.lower()
    summary = (notice.summary or "").lower()
    content = notice.content.lower()
    source = (normalize_facet_value(notice.source) or "").lower()
    category = (normalize_facet_value(notice.category) or "").lower()
    tags = " ".join(notice.tags).lower()
    full_text = build_search_text(notice)

    score = 0
    for term in terms:
        if term not in full_text:
            continue

        score += 1
        if term in title:
            score += 7
        if term in summary:
            score += 4
        if term in tags:
            score += 3
        if term in source or term in category:
            score += 2
        if term in content:
            score += 1

    return score


def filter_notices(
    notices: list[Notice],
    *,
    q: str | None = None,
    source: str | None = None,
    department: str | None = None,
    category: str | None = None,
) -> list[Notice]:
    source_filter = normalize_filter_value(source)
    department_filter = normalize_filter_value(department)
    category_filter = normalize_filter_value(category)
    terms = extract_search_terms(q)
    normalized_query = normalize_whitespace(q or "").lower()
    compact_query = compact(normalized_query)

    filtered: list[Notice] = []
    for notice in notices:
        source_names = get_notice_source_names(notice)
        notice_department = normalize_facet_value(notice.department)
        notice_category = normalize_facet_value(notice.category)

        if source_filter and source_filter not in source_names:
            continue

        if department_filter and notice_department != department_filter:
            continue

        if category_filter and notice_category != category_filter:
            continue

        if not normalized_query:
            filtered.append(notice)
            continue

        searchable = build_search_text(notice)
        if normalized_query in searchable:
            filtered.append(notice)
            continue

        compact_searchable = compact(searchable)
        if compact_query and compact_query in compact_searchable:
            filtered.append(notice)
            continue

        if not terms:
            continue

        matched_count = 0
        for term in terms:
            if term in searchable:
                matched_count += 1
                continue

            compact_term = compact(term)
            if compact_term and compact_term in compact_searchable:
                matched_count += 1

        required_matches = min(2, len(terms))
        if matched_count >= required_matches:
            filtered.append(notice)

    return filtered


def to_comparable_date(value: str | None = None) -> float:
    if not value:
        return 0

    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0


def rank_notices(notices: list[Notice], q: str | None = None) -> list[RankedNotice]:
    terms = [term.strip().lower() for term in extract_search_terms(q)]
    ranked = [RankedNotice(notice=notice, score=score_notice(notice, terms)) for notice in notices]
    return sorted(
        ranked,
        key=lambda item: (
            -(item.score if terms else 0),
            -to_comparable_date(item.notice.date),
            item.notice.title,
        ),
    )

