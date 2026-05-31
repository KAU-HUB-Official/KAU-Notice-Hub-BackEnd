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


def test_normalize_uses_image_fallback_when_markdown_image_is_removed() -> None:
    notice = normalize_notice(
        {
            "title": "이미지 Markdown 공지",
            "content": "![이미지](data:image/png;base64,AAAA)",
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


def test_normalize_promotes_empty_header_data_table() -> None:
    # 원본 헤더가 <td>라 markdownify가 빈 헤더를 만든 직사각형 데이터 표는
    # 첫 행을 헤더로 승격해 마크다운 표로 유지한다.
    notice = normalize_notice(
        {
            "title": "입상자 발표",
            "content": (
                "다음과 같이 발표합니다.\n\n"
                "|  |  |  |\n"
                "| --- | --- | --- |\n"
                "| 구분 | 성명 | 제안 교과목명 |\n"
                "| 최우수 | 배OO | 과학 수사와 프로파일링 |\n"
                "| 우수 | 김OO | 콘텐츠 기획 |"
            ),
        },
        0,
    )

    assert "|  |  |  |" not in notice.content
    assert "| 구분 | 성명 | 제안 교과목명 |" in notice.content
    assert "| --- | --- | --- |" in notice.content
    assert "| 최우수 | 배OO | 과학 수사와 프로파일링 |" in notice.content
    assert "| 우수 | 김OO | 콘텐츠 기획 |" in notice.content


def test_normalize_flattens_empty_header_flow_table_with_arrows() -> None:
    # 화살표가 든 흐름/공정 표는 직사각형이어도 표로 승격하지 않고 평문화한다.
    notice = normalize_notice(
        {
            "title": "제출절차",
            "content": (
                "|  |  |  |\n"
                "| --- | --- | --- |\n"
                "| 작성 | → | 접수 |\n"
                "| 검토 | → | 완료 |"
            ),
        },
        0,
    )

    assert "| --- |" not in notice.content
    assert "작성 → 접수" in notice.content


def test_normalize_splits_attached_number_section_markers() -> None:
    # 공백 없이 앞 텍스트에 붙은 번호 섹션 마커도 줄바꿈으로 분리한다.
    notice = normalize_notice(
        {
            "title": "공지",
            "content": (
                "안내문 참조2. 강의기간 안내 수강 불가5.성적처리 안내 (필독!!!)4. 학점"
            ),
        },
        0,
    )

    assert "참조\n2. 강의기간" in notice.content
    assert "불가\n5.성적처리" in notice.content
    assert ")\n4. 학점" in notice.content


def test_normalize_keeps_dates_intact() -> None:
    # 날짜(2026.06.09)·소수는 번호 섹션 마커로 오인해 끊으면 안 됨
    notice = normalize_notice(
        {"title": "공지", "content": "신청 기한 2026.06.09. 까지 평점 3.5 이상"},
        0,
    )

    assert "2026.06.09." in notice.content
    assert "3.5 이상" in notice.content


def test_normalize_keeps_spaced_date_followed_by_hangul() -> None:
    # "2026. 08. 예정"의 월(08.)을 섹션 마커로 오인해 날짜를 끊으면 안 됨.
    # 문장 종결/한글 뒤 진짜 섹션 마커(6. 문의)는 분리해야 한다.
    notice = normalize_notice(
        {
            "title": "성적 통보",
            "content": "학점교류성적 통보는 2026. 08. 예정6. 문의 : 학사팀",
        },
        0,
    )

    assert "2026. 08. 예정" in notice.content
    assert "2026.\n08." not in notice.content
    assert "예정\n6. 문의" in notice.content


def test_normalize_converts_orphan_table_rows_to_text() -> None:
    notice = normalize_notice(
        {
            "title": "고아 표 행",
            "content": "| 등록기간 | 6. 9.(화) 09:00 ~ 10.(수) 16:30 | |",
        },
        0,
    )

    assert notice.content == "등록기간 6. 9.(화) 09:00 ~ 10.(수) 16:30"


def test_normalize_removes_empty_orphan_table_rows() -> None:
    notice = normalize_notice(
        {
            "title": "빈 표 행",
            "content": "앞 문장\n|  |\n뒤 문장",
        },
        0,
    )

    assert notice.content == "앞 문장\n\n뒤 문장"


def test_normalize_splits_inline_circle_markers() -> None:
    notice = normalize_notice(
        {
            "title": "동그라미 항목",
            "content": "11:30~12:30 ○ 탑승자 확인○ 오리엔테이션",
        },
        0,
    )

    assert notice.content == "11:30~12:30\n○ 탑승자 확인\n○ 오리엔테이션"


def test_normalize_preserves_valid_markdown_table() -> None:
    raw = "| 구분 | 일정 |\n| --- | --- |\n| 신청 | 5/30 |"

    notice = normalize_notice({"title": "표", "content": raw}, 0)

    assert notice.content == raw


def test_normalize_escapes_non_url_parenthetical_link() -> None:
    notice = normalize_notice(
        {
            "title": "의도치 않은 링크",
            "content": "과거 [반도체 소자공정 실습](구. 반도체공정) 교과목",
        },
        0,
    )

    assert notice.content == r"과거 \[반도체 소자공정 실습](구. 반도체공정) 교과목"


def test_normalize_preserves_blank_lines_when_run_twice() -> None:
    raw = "문단1\n\n문단2\n\n1. 항목"

    once = normalize_notice({"title": "본문", "content": raw}, 0).content
    twice = normalize_notice({"title": "본문", "content": once}, 0).content

    assert once == raw
    assert twice == raw


def test_normalize_repairs_markdown_syntax_hazards() -> None:
    notice = normalize_notice(
        {
            "title": "깨진 Markdown",
            "content": (
                "<!-- comment -->\n"
                "![이미지](data:image/png;base64,AAAA)\n"
                "![]()\n"
                "공고명: 청년 매입임대 공고(`25년 2차)\n"
                "[상세](https://example.com/path\n"
                "첨부파일 참조![(붙임"
            ),
        },
        0,
    )

    assert "comment" not in notice.content
    assert "data:image" not in notice.content
    assert "![]()" not in notice.content
    assert r"공고명: 청년 매입임대 공고(\`25년 2차)" in notice.content
    assert "[상세](https://example.com/path)" in notice.content
    assert r"첨부파일 참조!\[(붙임" in notice.content
