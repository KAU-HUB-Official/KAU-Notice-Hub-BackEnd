from app.normalize import normalize_notice


def test_normalize_source_string_and_summary() -> None:
    notice = normalize_notice(
        {
            "title": "수강신청 안내",
            "content": "<p>수강신청 기간을 확인하세요.</p>",
            "source_name": "한국항공대학교 공식 홈페이지",
            "category_raw": "학사",
            "published_at": "2026-04-20T10:00:00+09:00",
            "original_url": "https://example.com/notices/1",
            "attachments": ["https://example.com/file.pdf"],
        },
        0,
    )

    assert notice.title == "수강신청 안내"
    assert notice.source == "한국항공대학교 공식 홈페이지"
    assert notice.sources == ["한국항공대학교 공식 홈페이지"]
    assert notice.category == "학사"
    assert notice.date == "2026-04-20"
    assert notice.summary == "수강신청 기간을 확인하세요."
    assert notice.tags == ["학사", "한국항공대학교 공식 홈페이지"]
    assert notice.attachments[0].name == "첨부파일"


def test_normalize_source_array_is_preserved() -> None:
    notice = normalize_notice(
        {
            "subject": "복수 학과 공지",
            "body": "본문",
            "source_name": [
                "한국항공대학교 컴퓨터공학과",
                "한국항공대학교 소프트웨어학과",
            ],
            "date": "2026-04-21",
        },
        0,
    )

    assert notice.source == "한국항공대학교 컴퓨터공학과"
    assert notice.sources == [
        "한국항공대학교 컴퓨터공학과",
        "한국항공대학교 소프트웨어학과",
    ]
    assert notice.tags == [
        "한국항공대학교 컴퓨터공학과",
        "한국항공대학교 소프트웨어학과",
    ]


def test_normalize_generates_fallback_fields() -> None:
    notice = normalize_notice({}, 2)

    assert notice.title == "제목 없음 공지 3"
    assert notice.content == "본문 정보가 비어 있습니다."
    assert notice.id.startswith("제목-없음-공지-3")
    assert notice.tags == []
    assert notice.attachments == []

