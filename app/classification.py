from __future__ import annotations

import re
from typing import Any

from app.schemas import Notice


ALL_SOURCES = "__ALL_SOURCES__"
ALL_DEPARTMENTS = "__ALL_DEPARTMENTS__"
ALL_CATEGORIES = "__ALL_CATEGORIES__"
ALL_AUDIENCE_GROUPS = "__ALL_AUDIENCES__"
ALL_SOURCE_GROUPS = "__ALL_SOURCE_GROUPS__"
DEPARTMENT_AUDIENCE_GROUP = "학부 재학생(학과/전공별)"

AUDIENCE_GROUP_ORDER = [
    "전 구성원 공통",
    DEPARTMENT_AUDIENCE_GROUP,
    "신입생·저학년",
    "재학생 비교과·글로벌 프로그램",
    "취업·창업 준비생",
    "대학원생",
    "평생·전문교육원",
    "그 외",
]

SOURCE_GROUP_ORDER = [
    "일반",
    "학사",
    "장학/대출",
    "입찰",
    "행사",
    "공과대",
    "AI융합대",
    "항공경영대",
    "그 외 학부",
    "새내기성공센터",
    "드림칼리지디자인",
    "국제교류",
    "첨단분야 부트캠프",
    "산학협력",
    "교수학습센터",
    "대학일자리플러스센터",
    "학과 취업공지",
    "대학원",
    "생활관",
    "인권센터",
    "학술정보관",
    "LMS",
    "입학처",
    "박물관",
    "그 외",
]

EMPTY_TOKENS = {"", "-", "_", "n/a", "na", "none", "null", "undefined", "미분류"}

ALL_FILTER_TOKENS = {
    ALL_SOURCES.lower(),
    ALL_DEPARTMENTS.lower(),
    ALL_CATEGORIES.lower(),
    ALL_AUDIENCE_GROUPS.lower(),
    ALL_SOURCE_GROUPS.lower(),
    "all",
    "전체",
    "전체출처",
    "전체 출처",
    "전체홈페이지",
    "전체 홈페이지",
    "전체중분류",
    "전체 중분류",
    "전체그룹",
    "전체 그룹",
    "전체부서",
    "전체 부서",
    "전체분류",
    "전체 분류",
}


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_token(value: str) -> str:
    return normalize_whitespace(value).lower()


def compact(value: str) -> str:
    return re.sub(r"\s+", "", value)


def unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def includes_any(value: str, candidates: list[str]) -> bool:
    return any(candidate in value for candidate in candidates)


def ordered_by_known_groups(values: list[str], order: list[str]) -> list[str]:
    order_index = {value: index for index, value in enumerate(order)}
    known = sorted(
        [value for value in values if value in order_index],
        key=lambda value: order_index[value],
    )
    unknown = sorted([value for value in values if value not in order_index])
    return [*known, *unknown]


def _field(notice: Notice | dict[str, Any], name: str) -> Any:
    if isinstance(notice, dict):
        return notice.get(name)
    return getattr(notice, name, None)


def normalize_facet_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = normalize_whitespace(value)
    if not normalized:
        return None

    if normalized.lower() in EMPTY_TOKENS:
        return None

    return normalized


def normalize_filter_value(value: Any) -> str | None:
    normalized = normalize_facet_value(value)
    if not normalized:
        return None

    if normalize_token(normalized) in ALL_FILTER_TOKENS:
        return None

    return normalized


def normalize_filter_values(value: Any) -> list[str]:
    raw_values = value if isinstance(value, list) else [value]
    normalized_values: list[str] = []
    for item in raw_values:
        if not isinstance(item, str):
            continue

        for part in item.split(","):
            normalized = normalize_filter_value(part)
            if normalized:
                normalized_values.append(normalized)

    return unique_preserve_order(normalized_values)


def should_use_source_filter(audience_group: str | None = None) -> bool:
    normalized_audience = normalize_filter_value(audience_group)
    return normalized_audience in {
        DEPARTMENT_AUDIENCE_GROUP,
        "대학원생",
        "평생·전문교육원",
    }


def get_notice_source_names(notice: Notice | dict[str, Any]) -> list[str]:
    raw_sources = _field(notice, "sources")
    from_list = []
    if isinstance(raw_sources, list):
        from_list = [
            normalized
            for source in raw_sources
            if (normalized := normalize_facet_value(source))
        ]

    fallback = normalize_facet_value(_field(notice, "source"))
    return unique_preserve_order([*from_list, fallback] if fallback else from_list)


def normalize_source_input(source: str | list[str] | None) -> list[str]:
    if isinstance(source, list):
        return unique_preserve_order(
            [
                normalized
                for item in source
                if (normalized := normalize_facet_value(item))
            ]
        )

    normalized = normalize_facet_value(source)
    return [normalized] if normalized else []


def source_text(sources: list[str]) -> str:
    return " ".join(sources)


def classify_source_to_audience(source: str | list[str] | None = None) -> str:
    sources = normalize_source_input(source)
    if not sources:
        return "그 외"

    text = source_text(sources)

    if includes_any(text, ["신소재공학과 취업공지", "대학일자리플러스센터"]):
        return "취업·창업 준비생"

    if includes_any(text, ["드림칼리지디자인", "새내기성공센터"]):
        return "신입생·저학년"

    if includes_any(text, ["국제교류처", "부트캠프사업단", "산학협력단", "교수학습센터"]):
        return "재학생 비교과·글로벌 프로그램"

    if includes_any(text, ["대학원", "정책대학원", "경영대학원"]):
        return "대학원생"

    if includes_any(
        text,
        [
            "평생교육원",
            "비행교육원",
            "항공교통관제교육원",
            "항공기술교육원",
            "항공안전교육원",
        ],
    ):
        return "평생·전문교육원"

    if includes_any(
        text,
        [
            "학과",
            "학부",
            "전공",
            "공과대학",
            "항공·경영대학",
            "항공경영대학",
            "AI융합대학",
            "인문자연학부",
            "자유전공학부",
        ],
    ):
        return DEPARTMENT_AUDIENCE_GROUP

    if any(item == "한국항공대학교 공식 홈페이지" for item in sources):
        return "전 구성원 공통"

    return "그 외"


def classify_notice_audience(notice: Notice | dict[str, Any]) -> str:
    return classify_source_to_audience(get_notice_source_names(notice))


def classify_common_notice_group(notice: Notice | dict[str, Any]) -> str:
    value = f"{normalize_facet_value(_field(notice, 'category')) or ''} {_field(notice, 'title') or ''}"

    if includes_any(value, ["입찰"]):
        return "입찰"

    if includes_any(value, ["학사", "수강", "졸업", "성적", "등록"]):
        return "학사"

    if includes_any(value, ["장학", "대출", "국가근로"]):
        return "장학/대출"

    if includes_any(value, ["행사", "특강", "설명회", "세미나"]):
        return "행사"

    return "일반"


def classify_college_groups(sources: list[str]) -> list[str]:
    groups: set[str] = set()

    for source in sources:
        if includes_any(
            source,
            [
                "공과대학",
                "항공우주공학",
                "기계항공공학",
                "항공우주및기계공학",
                "항공공학전공",
                "기계공학전공",
                "항공MRO전공",
                "우주공학전공",
                "신소재공학과 학부",
                "우주항공신소재전공",
                "반도체신소재전공",
            ],
        ):
            groups.add("공과대")
            continue

        if includes_any(
            source,
            [
                "AI융합대학",
                "AI융합ICT전공",
                "AI자율주행시스템공학과",
                "인공지능전공",
                "소프트웨어학과",
                "컴퓨터공학",
                "전기전자공학",
                "전자및항공전자전공",
                "항공전자정보공학부",
                "반도체시스템전공",
                "스마트드론공학과",
            ],
        ):
            groups.add("AI융합대")
            continue

        if includes_any(
            source,
            [
                "항공·경영대학",
                "항공경영대학",
                "항공경영",
                "경영학",
                "경영전공",
                "항공교통물류학부",
                "항공교통전공",
                "물류전공",
                "항공운항학과",
            ],
        ):
            groups.add("항공경영대")
            continue

        if includes_any(source, ["인문자연학부", "자유전공학부"]):
            groups.add("그 외 학부")

    return ordered_by_known_groups(list(groups), SOURCE_GROUP_ORDER)


def classify_notice_source_groups(notice: Notice | dict[str, Any]) -> list[str]:
    sources = get_notice_source_names(notice)
    audience = classify_notice_audience(notice)
    text = source_text(sources)

    if audience == "전 구성원 공통":
        return [classify_common_notice_group(notice)]

    if audience == DEPARTMENT_AUDIENCE_GROUP:
        groups = classify_college_groups(sources)
        return groups if groups else ["그 외 학부"]

    if audience == "신입생·저학년":
        if includes_any(text, ["새내기성공센터"]):
            return ["새내기성공센터"]
        if includes_any(text, ["드림칼리지디자인"]):
            return ["드림칼리지디자인"]

    if audience == "재학생 비교과·글로벌 프로그램":
        groups = set()
        if includes_any(text, ["국제교류처"]):
            groups.add("국제교류")
        if includes_any(text, ["부트캠프사업단"]):
            groups.add("첨단분야 부트캠프")
        if includes_any(text, ["산학협력단"]):
            groups.add("산학협력")
        if includes_any(text, ["교수학습센터"]):
            groups.add("교수학습센터")
        return ordered_by_known_groups(list(groups), SOURCE_GROUP_ORDER) if groups else ["그 외"]

    if audience == "취업·창업 준비생":
        groups = set()
        if includes_any(text, ["대학일자리플러스센터"]):
            groups.add("대학일자리플러스센터")
        if includes_any(text, ["신소재공학과 취업공지"]):
            groups.add("학과 취업공지")
        return ordered_by_known_groups(list(groups), SOURCE_GROUP_ORDER)

    if audience in {"대학원생", "평생·전문교육원"}:
        return []

    if audience == "그 외":
        groups = set()
        if includes_any(text, ["생활관"]):
            groups.add("생활관")
        if includes_any(text, ["인권센터"]):
            groups.add("인권센터")
        if includes_any(text, ["학술정보관"]):
            groups.add("학술정보관")
        if includes_any(text, ["LMS"]):
            groups.add("LMS")
        if includes_any(text, ["입학처"]):
            groups.add("입학처")
        if includes_any(text, ["항공우주박물관"]):
            groups.add("박물관")
        return ordered_by_known_groups(list(groups), SOURCE_GROUP_ORDER)

    return ["그 외"]


def classify_notice_source_group(notice: Notice | dict[str, Any]) -> str | None:
    groups = classify_notice_source_groups(notice)
    return groups[0] if groups else None


def _unique_sorted(values: list[str | None]) -> list[str]:
    return sorted({value for value in values if value})


def get_all_audience_groups(notices: list[Notice]) -> list[str]:
    present = {classify_notice_audience(notice) for notice in notices}
    return [group for group in AUDIENCE_GROUP_ORDER if group in present]


def filter_by_audience_group(notices: list[Notice], audience_group: str | None) -> list[Notice]:
    normalized_audience = normalize_filter_value(audience_group)
    if not normalized_audience:
        return notices
    return [
        notice
        for notice in notices
        if classify_notice_audience(notice) == normalized_audience
    ]


def get_all_source_groups(notices: list[Notice]) -> list[str]:
    present: set[str] = set()
    for notice in notices:
        present.update(classify_notice_source_groups(notice))
    return ordered_by_known_groups(list(present), SOURCE_GROUP_ORDER)


def filter_by_source_group(notices: list[Notice], source_group: str | None) -> list[Notice]:
    normalized_source_group = normalize_filter_value(source_group)
    if not normalized_source_group:
        return notices
    return [
        notice
        for notice in notices
        if normalized_source_group in classify_notice_source_groups(notice)
    ]


def _with_single_source(notice: Notice, source: str) -> Notice:
    return notice.model_copy(update={"source": source, "sources": [source]})


def get_facet_source_names(
    notice: Notice,
    audience_group: str | None = None,
    source_group: str | None = None,
) -> list[str]:
    normalized_audience = normalize_filter_value(audience_group)
    normalized_source_group = normalize_filter_value(source_group)
    sources = get_notice_source_names(notice)
    scoped_sources: list[str] = []

    for source in sources:
        scoped_notice = _with_single_source(notice, source)
        if normalized_audience and classify_notice_audience(scoped_notice) != normalized_audience:
            continue

        if normalized_source_group and normalized_source_group not in classify_notice_source_groups(
            scoped_notice
        ):
            continue

        scoped_sources.append(source)

    return scoped_sources if scoped_sources else sources


def get_all_sources(
    notices: list[Notice],
    audience_group: str | None = None,
    source_group: str | None = None,
) -> list[str]:
    values: list[str] = []
    for notice in notices:
        values.extend(get_facet_source_names(notice, audience_group, source_group))
    return _unique_sorted(values)


def get_all_departments(notices: list[Notice]) -> list[str]:
    return _unique_sorted([normalize_facet_value(notice.department) for notice in notices])


def is_category_shape_useful(value: str) -> bool:
    if len(value) < 2 or len(value) > 24:
        return False
    return not bool(re.search(r"[<>]", value))


def get_clean_categories(notices: list[Notice]) -> list[str]:
    categories = [
        normalized
        for notice in notices
        if (normalized := normalize_facet_value(notice.category))
    ]
    if not categories:
        return []

    count_map: dict[str, int] = {}
    for category in categories:
        count_map[category] = count_map.get(category, 0) + 1

    entries = list(count_map.items())
    one_off_count = len([entry for entry in entries if entry[1] == 1])
    one_off_ratio = one_off_count / len(entries)

    cleaned = sorted(
        [
            category
            for category, count in entries
            if count >= 2 and is_category_shape_useful(category)
        ]
    )

    if not cleaned:
        return []

    if len(entries) > 18 or one_off_ratio > 0.35:
        return []

    return cleaned[:12]


def format_source_label(source: str) -> str:
    normalized = normalize_whitespace(source)
    compacted = re.sub(r"^한국항공대학교\s*", "", normalized)
    return compacted or normalized

