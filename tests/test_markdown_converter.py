from bs4 import BeautifulSoup

from app.crawler.utils.markdown_converter import (
    html_node_to_markdown,
    make_image_only_markdown,
)


def _node(html: str):
    return BeautifulSoup(html, "html.parser").select_one("div")


def test_html_node_to_markdown_basic_blocks() -> None:
    node = _node(
        "<div><h2>제목</h2><p>본문 단락.</p><ul><li>가</li><li>나</li></ul></div>"
    )
    md = html_node_to_markdown(node)
    assert md.splitlines() == [
        "## 제목",
        "",
        "본문 단락.",
        "",
        "- 가",
        "- 나",
    ]


def test_html_node_to_markdown_absolutizes_urls() -> None:
    node = _node(
        '<div><a href="/notice/1">상세</a> <img src="img.png" alt="포스터"></div>'
    )
    md = html_node_to_markdown(node, base_url="https://kau.ac.kr/board/list")
    assert "[상세](https://kau.ac.kr/notice/1)" in md
    assert "![포스터](https://kau.ac.kr/board/img.png)" in md


def test_html_node_to_markdown_drops_script_and_style() -> None:
    node = _node(
        "<div><p>본문</p><script>alert(1)</script><style>p{}</style></div>"
    )
    assert html_node_to_markdown(node) == "본문"


def test_html_node_to_markdown_preserves_table() -> None:
    node = _node(
        "<div><table><thead><tr><th>구분</th><th>일정</th></tr></thead>"
        "<tbody><tr><td>신청</td><td>5/30</td></tr></tbody></table></div>"
    )
    md = html_node_to_markdown(node)
    assert "| 구분 | 일정 |" in md
    assert "| 신청 | 5/30 |" in md


def test_html_node_to_markdown_handles_none_and_empty() -> None:
    assert html_node_to_markdown(None) == ""
    assert html_node_to_markdown(_node("<div></div>")) == ""
    assert html_node_to_markdown(_node("<div>   </div>")) == ""


def test_make_image_only_markdown_with_alt_and_limit() -> None:
    soup = BeautifulSoup(
        "<div>"
        + "".join(
            f'<img src="/img/{i}.png" alt="포스터{i}">' for i in range(12)
        )
        + "</div>",
        "html.parser",
    )
    md = make_image_only_markdown(
        soup.select("img"), base_url="https://kau.ac.kr/page", limit=10
    )
    lines = md.split("\n\n")
    assert lines[0] == "![포스터0](https://kau.ac.kr/img/0.png)"
    assert lines[9] == "![포스터9](https://kau.ac.kr/img/9.png)"
    assert lines[-1] == "_… 외 이미지 2장_"


def test_make_image_only_markdown_dedupes_by_src() -> None:
    soup = BeautifulSoup(
        '<div><img src="a.png" alt="A"><img src="a.png" alt="B"></div>',
        "html.parser",
    )
    md = make_image_only_markdown(soup.select("img"), base_url="https://x.test/")
    assert md == "![A](https://x.test/a.png)"


def test_make_image_only_markdown_returns_empty_when_no_src() -> None:
    soup = BeautifulSoup('<div><img alt="A"></div>', "html.parser")
    assert make_image_only_markdown(soup.select("img")) == ""


def test_normalize_bullet_impersonation_in_strong() -> None:
    # `<strong>-</strong>제출항목` 같은 패턴이 진짜 bullet으로 풀려야 함
    node = _node(
        "<div><p>아래 구글폼 항목을 작성하여 기한 내 제출해주시기 바랍니다.</p>"
        "<p><strong>-</strong>제출항목 : 필명 / 소속 / 학번</p></div>"
    )
    md = html_node_to_markdown(node)
    assert "- 제출항목 : 필명 / 소속 / 학번" in md
    assert "**-**" not in md


def test_normalize_various_bullet_glyphs_in_strong() -> None:
    node = _node(
        "<div>"
        "<p><strong>•</strong>대상</p>"
        "<p><strong>▪</strong>일정</p>"
        "<p><strong>○</strong>장소</p>"
        "</div>"
    )
    md = html_node_to_markdown(node)
    for line in ["- 대상", "- 일정", "- 장소"]:
        assert line in md, f"{line!r} not in markdown:\n{md}"


def test_normalize_decorative_only_strong_is_stripped() -> None:
    node = _node(
        "<div>"
        "<p><strong>:</strong>안녕</p>"
        "<p><strong>  </strong>빈 강조</p>"
        "</div>"
    )
    md = html_node_to_markdown(node)
    assert ":안녕" in md
    assert "빈 강조" in md
    assert "**" not in md


def test_normalize_cjk_adjacent_strong_is_unwrapped() -> None:
    # CommonMark left/right-flanking rule을 한국어에서 위반하는 패턴
    node = _node(
        "<div>"
        "<p>이것은 <strong>매우 중요한</strong>안내입니다.</p>"
        "<p>마감<strong>5월 31일</strong>까지</p>"
        "</div>"
    )
    md = html_node_to_markdown(node)
    assert "매우 중요한안내" in md
    assert "마감5월 31일까지" in md
    assert "**" not in md


def test_split_inline_bullets_after_multispace() -> None:
    # <p>안에 &nbsp; 시퀀스로 들여쓰기를 흉내낸 패턴
    node = _node(
        "<div><p>스토어:&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
        "• 이케아 고양점, 이케아 강동점</p></div>"
    )
    md = html_node_to_markdown(node)
    assert "스토어:" in md
    assert "\n• 이케아 고양점" in md or "스토어:\n• 이케아 고양점" in md


def test_split_inline_bullets_after_closing_punctuation() -> None:
    # (예정)- 모집 부분 → 줄바꿈
    node = _node(
        "<div><p>모집 기간: 2026.5.15 - 6.10 (예정)- 모집 부분: 물류</p></div>"
    )
    md = html_node_to_markdown(node)
    assert "(예정)\n- 모집 부분" in md


def test_split_inline_bullets_dash_with_label() -> None:
    # 단어 + - + 라벨: → 줄바꿈
    node = _node(
        "<div><p>물류/ 세일즈/ 이케아 푸드 인턴- 인턴십 기간: 2026 년 7 월</p></div>"
    )
    md = html_node_to_markdown(node)
    assert "인턴\n- 인턴십 기간" in md


def test_split_inline_bullets_preserves_date_ranges() -> None:
    # 정상 dash 범위 표현은 깨면 안 됨
    cases = [
        "<p>기간: 2026.5 - 6.10</p>",
        "<p>오늘 - 내일</p>",
        "<p>2026 년 7 월 - 12 월</p>",
        "<p>- 모집 기간: 5월</p>",  # 라인 시작 정상 bullet
    ]
    for html in cases:
        md = html_node_to_markdown(_node(f"<div>{html}</div>"))
        assert "\n-" not in md and "\n•" not in md, f"잘못 분리됨: {html} → {md!r}"


def test_split_inline_bullets_user_ikea_case() -> None:
    # 사용자가 실제로 발견한 케이스 시뮬레이션 (한 단락 통째)
    inline = (
        "(이케아 코리아 인턴십 - 스토어 현장에서 리테일의 기초를 배우고, "
        "어디서든 통하는 커리어를 시작하세요.)      - 모집 기간: 2026 년 5 월 15 일 - "
        "6 월 10 일 (예정)- 모집 부분: 물류/ 세일즈/ 이케아 푸드 인턴- 인턴십 기간: "
        "2026 년 7 월 - 12 월- 인턴십 운영 스토어:        • 이케아 고양점, 이케아 강동점"
        "     - 자격        • 나이, 학력, 전공, 어학 성적 무관"
    )
    node = _node(f"<div><p>{inline}</p></div>")
    md = html_node_to_markdown(node)
    # 사용자 시각으로 의미 단위가 줄바꿈으로 분리됐는지
    for fragment in [
        "- 모집 기간:",
        "- 모집 부분:",
        "- 인턴십 기간:",
        "- 인턴십 운영 스토어:",
        "• 이케아 고양점",
        "- 자격",
        "• 나이, 학력, 전공",
    ]:
        assert fragment in md, f"{fragment!r} 누락"
    # 정상 dash (스토어 현장에서 -, 5 월 15 일 -, 7 월 -)는 보존
    assert "인턴십 - 스토어" in md


def test_normalize_keeps_well_formed_strong() -> None:
    # 양쪽 공백 + 단독 strong은 정상 렌더되므로 보존
    node = _node(
        "<div>"
        "<p>이것은 <strong>매우 중요한</strong> 안내입니다.</p>"
        "<p><strong>중요 공지</strong></p>"
        "</div>"
    )
    md = html_node_to_markdown(node)
    assert "**매우 중요한**" in md
    assert "**중요 공지**" in md
