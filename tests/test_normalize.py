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
    assert notice.content == "수강신청 기간을 확인하세요."
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


def test_normalize_converts_raw_html_content_to_markdown() -> None:
    notice = normalize_notice(
        {
            "title": "HTML 본문",
            "content": "<p><strong>중요</strong><br>신청 안내</p>",
        },
        0,
    )

    assert notice.content == "**중요**\n신청 안내"
    assert "<p>" not in notice.content
    assert "<br" not in notice.content


def test_normalize_replaces_inline_br_in_markdown_table() -> None:
    notice = normalize_notice(
        {
            "title": "Markdown 표",
            "content": (
                "| 구분 | 요건 |\n"
                "| --- | --- |\n"
                "| 이수학점 | 2012학번까지 140학점<br>2013학번 이후 130학점 |"
            ),
        },
        0,
    )

    assert "<br" not in notice.content
    assert "| 이수학점 | 2012학번까지 140학점 / 2013학번 이후 130학점 |" in notice.content


def test_normalize_uses_image_fallback_for_data_uri_html() -> None:
    notice = normalize_notice(
        {
            "title": "이미지 공지",
            "content": '<p><img src="data:image/png;base64,AAAA" alt="본문"></p>',
        },
        0,
    )

    assert notice.content == "**[이미지 본문]**\n\n원문 공지에서 이미지를 확인해주세요."
    assert "data:image" not in notice.content


def test_normalize_splits_decorative_section_and_inline_numbered_items() -> None:
    notice = normalize_notice(
        {
            "title": "AI융합전공 이수 신청 안내",
            "content": (
                "절차 안내를 아래와 같이 공고합니다. - 아 래 - 1. 제출대상자 : "
                "2026년 8월 졸업 예정자 ▪ 융합전공 이수요건 : 전공학점 36학점 "
                "※ 포기자는 포기원 제출 2. 제출 기간 : 2026. 6. 30(화) ~ 7. 6(월) "
                "3. 제출 서류 : 이수확인서 1부 4. 제출절차 이수확인서 작성 → "
                "▪ e-mail접수 knyoon@kau.ac.kr ▪ 융합전공 사무실 접수 5. 문의 사항 "
                "▪ 각 전공별 문의 : 해당 전공주임교수 - AI융합경영전공 김진기 교수"
            ),
        },
        0,
    )

    assert "- 아 래 - 1." not in notice.content
    assert "아래\n\n1. 제출대상자" in notice.content
    assert "\n▪ 융합전공 이수요건" in notice.content
    assert "\n※ 포기자는 포기원 제출\n2. 제출 기간" in notice.content
    assert "\n3. 제출 서류" in notice.content
    assert "\n4. 제출절차\n이수확인서 작성" in notice.content
    assert "\n▪ e-mail접수" in notice.content
    assert "\n5. 문의 사항" in notice.content
    assert "해당 전공주임교수\n- AI융합경영전공" in notice.content


def test_normalize_splits_repeated_major_professor_dash_items() -> None:
    notice = normalize_notice(
        {
            "title": "전공별 문의",
            "content": (
                "▪ 각 전공별 문의 : 해당 전공주임교수 - AI 융합경영전공 김진기 교수 "
                "( kimjk@kau.ac.kr ) - AI 융합물류전공 채준재 교수 "
                "( jchae@kau.ac.kr ) - IT-Biz 융합전공 김진기 교수 "
                "( kimjk@kau.ac.kr )"
            ),
        },
        0,
    )

    assert "해당 전공주임교수\n- AI 융합경영전공" in notice.content
    assert "\n- AI 융합물류전공" in notice.content
    assert "\n- IT-Biz 융합전공" in notice.content


def test_normalize_converts_empty_header_flow_table_to_text() -> None:
    notice = normalize_notice(
        {
            "title": "제출절차",
            "content": (
                "4. 제출절차\n"
                "|  |  |  |  |  |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| 이수확인서 작성 및 성적증명서 발급 | → | 주임교수 이수 확인 | → | "
                "▪e-mail접수 [jchae@kau.ac.kr](mailto:bmsong@kau.ac.kr)  ▪사무실 접수 |\n"
                "| 별첨 양식 다운로드 |\n"
                "5. 문의 사항"
            ),
        },
        0,
    )

    assert "| --- |" not in notice.content
    assert "4. 제출절차\n이수확인서 작성 및 성적증명서 발급 → 주임교수 이수 확인 →" in notice.content
    assert "\n▪ e-mail접수 [jchae@kau.ac.kr](mailto:jchae@kau.ac.kr)" in notice.content
    assert "\n▪ 사무실 접수" in notice.content
    assert "\n별첨 양식 다운로드\n5. 문의 사항" in notice.content


def test_normalize_preserves_blank_lines_when_run_twice() -> None:
    raw = "문단1\n\n문단2\n\n1. 항목"

    once = normalize_notice({"title": "본문", "content": raw}, 0).content
    twice = normalize_notice({"title": "본문", "content": once}, 0).content

    assert once == raw
    assert twice == raw
