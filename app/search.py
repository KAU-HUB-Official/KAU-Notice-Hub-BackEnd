from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_cls, datetime
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


def compact_search_text(searchable_text: str) -> str:
    return compact(searchable_text)


# 같은 의미군의 term들. 사용자가 한 표현만 검색해도 다른 표현이 들어간 공지가
# 매치되도록 SQL candidate 단계에서 OR로 확장된다.
SYNONYM_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"기숙사", "생활관"}),
    frozenset({"공모전", "대회", "경진대회", "공모"}),
    frozenset({"장학", "장학금", "장학생"}),
    frozenset({"입시", "입학", "신입생"}),
    # "기말고사"는 공지의 "기말시험"과 동의어다. 일반 "시험"까지 끌어오면
    # 무관한 시험(시험부 제작, 시험기간 행사 등)이 섞이므로 좁은 전용 군으로 둔다.
    frozenset({"기말고사", "기말시험"}),
    frozenset({"중간고사", "중간시험"}),
    frozenset({"시험", "기말시험", "중간시험"}),
    frozenset({"박람회", "설명회"}),
    frozenset({"AI융합대", "AI융합대학", "AI융합"}),
    frozenset({"항공경영대", "항공경영대학", "항공·경영대학"}),
    frozenset({"공과대", "공과대학"}),
    frozenset({"휴학", "휴학신청"}),
    frozenset({"복학", "복학신청"}),
    frozenset({"채용", "모집", "선발"}),
    frozenset({"인턴", "인턴십"}),
)


def expand_search_terms(terms: list[str]) -> list[str]:
    """`SYNONYM_GROUPS`에 해당하는 term을 같은 군의 다른 표현으로 확장한다.

    중복은 case-insensitive 기준으로 제거하고, 원래 term 순서를 보존한다.
    """
    expanded: list[str] = []
    seen: set[str] = set()
    for term in terms:
        if not term:
            continue
        lower = term.lower()
        if lower in seen:
            continue
        seen.add(lower)
        expanded.append(term)
        matched_group: frozenset[str] | None = None
        for group in SYNONYM_GROUPS:
            if lower in {member.lower() for member in group}:
                matched_group = group
                break
        if matched_group is None:
            continue
        for synonym in matched_group:
            if synonym.lower() in seen:
                continue
            seen.add(synonym.lower())
            expanded.append(synonym)
    return expanded


def recency_boost(notice_date: str, today: date_cls | None = None) -> int:
    parsed = datetime.fromisoformat(notice_date).date()
    reference = today or date_cls.today()
    delta_days = (reference - parsed).days
    if delta_days < 0:
        return 0
    if delta_days <= 7:
        return 5
    if delta_days <= 30:
        return 3
    if delta_days <= 90:
        return 1
    if delta_days > 365:
        return -2
    return 0


def score_notice(notice: Notice, terms: list[str], today: date_cls | None = None) -> int:
    if not terms:
        return 0

    title = notice.title.lower()
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
        if term in tags:
            score += 3
        if term in source or term in category:
            score += 2
        if term in content:
            score += 1

    if score > 0 and notice.date:
        score += recency_boost(notice.date, today)

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


def query_term_groups(q: str | None) -> list[list[str]]:
    """질의어를 동의어군 단위로 묶는다.

    각 그룹은 `score_by_groups`에서 한 번만 가산된다. 후보 선정은 동의어를 모두
    OR로 펼치지만(recall), 점수는 그룹당 1회만 줘서 "장학금"과 그 부분문자열
    "장학"이 같은 글자를 두 번 가산하는 문제를 막는다.
    """
    groups: list[list[str]] = []
    used: set[str] = set()
    for term in extract_search_terms(q):
        low = term.strip().lower()
        if not low or low in used:
            continue
        members = {low}
        for group in SYNONYM_GROUPS:
            if low in {member.lower() for member in group}:
                members |= {member.lower() for member in group}
                break
        used |= members
        groups.append(sorted(members))
    return groups


def score_by_groups(
    notice: Notice,
    groups: list[list[str]],
    today: date_cls | None = None,
) -> int:
    """동의어 그룹 단위 점수. 그룹 내 어떤 동의어가 매칭되든 필드당 1회만 가산한다."""
    if not groups:
        return 0

    title = notice.title.lower()
    content = notice.content.lower()
    source = (normalize_facet_value(notice.source) or "").lower()
    category = (normalize_facet_value(notice.category) or "").lower()
    tags = " ".join(notice.tags).lower()
    full_text = build_search_text(notice)

    score = 0
    for members in groups:
        if not any(member in full_text for member in members):
            continue
        score += 1
        if any(member in title for member in members):
            score += 7
        if any(member in tags for member in members):
            score += 3
        if any(member in source or member in category for member in members):
            score += 2
        if any(member in content for member in members):
            score += 1

    if score > 0 and notice.date:
        score += recency_boost(notice.date, today)

    return score


def rank_notices(
    notices: list[Notice],
    q: str | None = None,
    today: date_cls | None = None,
) -> list[RankedNotice]:
    # 후보 선정(_search_with_query)과 동일하게 동의어를 점수에 반영하되,
    # 그룹당 1회만 가산한다. 확장하지 않으면 "기말고사" 질의에서 "기말시험"
    # 공지가 점수 0으로 밀리고, 중복 가산하면 본문에 키워드가 여러 번 든
    # 오래된 공지가 최신 공지를 역전한다.
    groups = query_term_groups(q)
    ranked = [
        RankedNotice(notice=notice, score=score_by_groups(notice, groups, today))
        for notice in notices
    ]
    return sorted(
        ranked,
        key=lambda item: (
            -(item.score if groups else 0),
            -to_comparable_date(item.notice.date),
            item.notice.title,
        ),
    )

