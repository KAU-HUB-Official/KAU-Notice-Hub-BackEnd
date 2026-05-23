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
