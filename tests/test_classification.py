from app.classification import (
    DEPARTMENT_AUDIENCE_GROUP,
    classify_notice_audience,
    classify_notice_source_group,
    classify_notice_source_groups,
    get_all_sources,
    should_use_source_filter,
)
from app.schemas import Notice


def make_notice(
    *,
    title: str = "공지",
    source: str | None = None,
    sources: list[str] | None = None,
    category: str | None = None,
) -> Notice:
    return Notice(
        id=title,
        title=title,
        content="본문",
        source=source,
        sources=sources if sources is not None else ([source] if source else []),
        category=category,
        tags=[],
        attachments=[],
    )


def test_common_homepage_group_uses_category_and_title() -> None:
    notice = make_notice(
        title="2026학년도 수강신청 안내",
        source="한국항공대학교 공식 홈페이지",
        category="일반공지",
    )

    assert classify_notice_audience(notice) == "전 구성원 공통"
    assert classify_notice_source_group(notice) == "학사"


def test_department_source_maps_to_college_group() -> None:
    notice = make_notice(source="한국항공대학교 컴퓨터공학과")

    assert classify_notice_audience(notice) == DEPARTMENT_AUDIENCE_GROUP
    assert classify_notice_source_groups(notice) == ["AI융합대"]


def test_multi_source_notice_exposes_scoped_sources() -> None:
    notice = make_notice(
        sources=[
            "한국항공대학교 컴퓨터공학과",
            "한국항공대학교 신소재공학과 학부",
        ],
    )

    assert classify_notice_source_groups(notice) == ["공과대", "AI융합대"]
    assert get_all_sources([notice], DEPARTMENT_AUDIENCE_GROUP, "AI융합대") == [
        "한국항공대학교 컴퓨터공학과"
    ]


def test_graduate_and_lifelong_sources_use_source_filter_without_groups() -> None:
    graduate = make_notice(source="한국항공대학교 경영대학원")
    lifelong = make_notice(source="한국항공대학교 항공기술교육원")

    assert classify_notice_audience(graduate) == "대학원생"
    assert classify_notice_source_groups(graduate) == []
    assert classify_notice_audience(lifelong) == "평생·전문교육원"
    assert should_use_source_filter("대학원생")
    assert should_use_source_filter("평생·전문교육원")


def test_unknown_source_falls_back_to_other() -> None:
    notice = make_notice(source="알 수 없는 게시판")

    assert classify_notice_audience(notice) == "그 외"
    assert classify_notice_source_group(notice) is None
    assert not should_use_source_filter("그 외")

