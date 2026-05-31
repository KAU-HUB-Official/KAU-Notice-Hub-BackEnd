"""HTML 단편을 Markdown으로 변환하는 공용 유틸.

크롤러 각 파서는 본문 컨테이너 Tag를 찾고 이 모듈에 위임한다.
프론트엔드 상세 페이지가 Markdown renderer로 본문을 그리도록 맞춘 출력 포맷.
"""

from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from bs4.element import Tag
from markdownify import markdownify

# 출력에서 항상 제거할 태그. markdownify가 strip 옵션으로 처리한다.
_STRIP_TAGS: tuple[str, ...] = (
    "script",
    "style",
    "noscript",
    "iframe",
    "meta",
    "link",
)

# 절대 URL로 치환할 속성 매핑.
_URL_ATTRS: tuple[tuple[str, str], ...] = (
    ("a", "href"),
    ("img", "src"),
    ("img", "data-src"),
    ("source", "src"),
)


def html_node_to_markdown(
    node: Tag | str | None,
    *,
    base_url: str | None = None,
) -> str:
    """HTML 단편을 Markdown 문자열로 변환한다.

    - 상대 URL을 ``base_url`` 기준 절대 URL로 치환한다.
    - script/style/iframe 등은 제거.
    - 헤딩은 ATX(`#`) 스타일.
    - 3줄 이상 연속 공백 줄은 2줄로 압축, 양 끝 trim.
    """
    if node is None:
        return ""

    html = node.decode() if isinstance(node, Tag) else str(node)
    if not html.strip():
        return ""

    html = _preprocess(html, base_url=base_url)

    markdown = markdownify(
        html,
        heading_style="ATX",
        strip=list(_STRIP_TAGS),
        bullets="-",
    )
    markdown = _normalize_emphasis(markdown)
    markdown = _split_inline_bullets(markdown)
    markdown = _escape_unbalanced_backticks(markdown)
    return _collapse_blank_lines(markdown).strip()


def make_image_only_markdown(
    images: Iterable[Tag],
    *,
    base_url: str | None = None,
    limit: int = 10,
) -> str:
    """본문이 텍스트 없이 이미지로만 구성된 경우 사용하는 fallback Markdown."""
    rendered: list[str] = []
    overflow = 0
    seen: set[str] = set()
    for img in images:
        if not isinstance(img, Tag):
            continue
        src = (img.get("src") or img.get("data-src") or "").strip()
        if not src:
            continue
        if src.lower().startswith(("data:", "javascript:")):
            continue
        absolute = urljoin(base_url, src) if base_url else src
        absolute = _escape_markdown_url(absolute)
        if absolute in seen:
            continue
        seen.add(absolute)
        alt = (img.get("alt") or "").strip() or "이미지"
        if len(rendered) >= limit:
            overflow += 1
            continue
        rendered.append(f"![{_escape_alt(alt)}]({absolute})")
    if not rendered:
        return ""
    if overflow:
        rendered.append(f"_… 외 이미지 {overflow}장_")
    return "\n\n".join(rendered)


def _preprocess(html: str, *, base_url: str | None) -> str:
    soup = BeautifulSoup(html, "html.parser")

    # 본문 노이즈가 텍스트로 새지 않도록 완전히 제거한다.
    for tag in soup.find_all(list(_STRIP_TAGS)):
        tag.decompose()

    _normalize_image_sources(soup, base_url=base_url)

    for tag_name, attr in _URL_ATTRS:
        if tag_name == "img":
            continue
        for tag in soup.find_all(tag_name):
            value = (tag.get(attr) or "").strip()
            if not value:
                continue
            lowered = value.lower()
            if lowered.startswith("data:"):
                if tag_name in {"img", "source"}:
                    tag.decompose()
                else:
                    tag.attrs.pop(attr, None)
                continue
            if lowered.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
            if base_url:
                value = urljoin(base_url, value)
            tag[attr] = _escape_markdown_url(value)

    return soup.decode()


def _normalize_image_sources(soup: BeautifulSoup, *, base_url: str | None) -> None:
    """Choose a renderable image URL before markdownify sees the tree."""
    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        data_src = (img.get("data-src") or "").strip()
        candidate = _first_non_data_url(src, data_src)
        if not candidate:
            img.decompose()
            continue
        if base_url:
            candidate = urljoin(base_url, candidate)
        img["src"] = _escape_markdown_url(candidate)
        img.attrs.pop("data-src", None)


def _first_non_data_url(*values: str) -> str:
    for value in values:
        lowered = value.lower()
        if not value or lowered.startswith(("data:", "javascript:")):
            continue
        return value
    return ""


def _escape_markdown_url(value: str) -> str:
    return (
        value.replace(" ", "%20")
        .replace("(", "%28")
        .replace(")", "%29")
    )


def _collapse_blank_lines(text: str) -> str:
    text = text.replace("\r", "")
    return re.sub(r"\n{3,}", "\n\n", text)


# CJK 글자 (한글/한자/히라가나/가타가나)
_CJK_PATTERN = (
    r"[぀-ゟ"  # Hiragana
    r"゠-ヿ"  # Katakana
    r"㐀-䶿"  # CJK Extension A
    r"一-鿿"  # CJK Unified
    r"가-힯]"  # Hangul Syllables
)

# 강조 안에 의미 있는 문자가 없는 경우(공백/기호/구두점만)
_EMPHASIS_DECORATIVE_RE = re.compile(
    r"(\*\*|__)\s*([\-\*•▪○◇◆▶▷※·:;,.\s]*)\s*\1"
)

# bullet 흉내 — `**-**텍스트` 같은 패턴을 실제 dash + 공백 형태로 (라인 시작 한정)
_BULLET_LIKE_RE = re.compile(
    r"^(\s*)(?:\*\*|__)\s*([\-•▪○])\s*(?:\*\*|__)\s*",
    flags=re.MULTILINE,
)

# CJK 인접 강조 (CommonMark left/right flanking 위반): `한글**굵게**한글`
_CJK_LEFT_EMPHASIS_RE = re.compile(
    rf"(?<={_CJK_PATTERN})(\*\*|__)([^\n*_]+?)\1"
)
_CJK_RIGHT_EMPHASIS_RE = re.compile(
    rf"(\*\*|__)([^\n*_]+?)\1(?={_CJK_PATTERN})"
)


# 라인 안에 박힌 bullet 후보들 — `-`, `•`, `▪`, `○`, `◇`, `◆`
_INLINE_BULLET_CHARS = r"\-•▪○◇◆"

# 한국어 본문에서 거의 항상 "항목 구분" 의미로 쓰이는 bullet 글자.
# dash와 달리 단일 공백으로 분리해도 정상 표현이 깨질 위험이 낮다.
_SAFE_BULLET_CHARS = r"•▪○◇◆"

# 다중 공백 (2+) 다음에 bullet character + 공백/탭이 오면 줄바꿈으로 정규화.
# dash(`-`)는 "오늘 - 내일" 같은 정상 표현과 구분하려고 다중 공백 조건이 필요하다.
_MULTISPACE_BEFORE_BULLET_RE = re.compile(
    rf"(?<=\S)[ \t]{{2,}}(?=[{_INLINE_BULLET_CHARS}][ \t])"
)

# 안전한 bullet 글자(•/▪/○ 등)는 단일 공백으로도 분리한다.
# 예: "자격 • 나이 • 총 경력" → "자격\n• 나이\n• 총 경력"
_SINGLE_SPACE_BEFORE_SAFE_BULLET_RE = re.compile(
    rf"(?<=\S)[ \t]+(?=[{_SAFE_BULLET_CHARS}][ \t])"
)

# 닫는 괄호/종결 부호 직후 (공백 없거나 한 칸) bullet character가 오면 줄바꿈.
# 예: "(예정)- 모집 부분" → "(예정)\n- 모집 부분"
# 정상 표현 "오늘 - 내일" 같은 패턴을 보호하려고 종결 부호 뒤에만.
_CLOSING_BEFORE_BULLET_RE = re.compile(
    rf"(?<=[\)\]\.!?。．])[ \t]*(?=[{_INLINE_BULLET_CHARS}][ \t])"
)

# 단어 + 바로 붙은 "- 라벨:" 또는 "- 라벨 " 패턴 → 줄바꿈 추가.
# 예: "인턴- 인턴십 기간:" → "인턴\n- 인턴십 기간:"
#     "12 월- 인턴십 운영" → "12 월\n- 인턴십 운영"
# 정상 "오늘 - 내일", "2026.5 - 2026.6" 같은 표현은 dash 앞에 공백이 있어서 매치 안 됨.
_INLINE_DASH_LABEL_RE = re.compile(
    r"(?<=[^\s\-\d])(?=-[ \t]+[가-힣A-Za-z][가-힣A-Za-z\d]{0,14}[ \t:])"
)


def _split_inline_bullets(text: str) -> str:
    """원본 HTML이 <br> 없이 &nbsp; 시퀀스로 줄바꿈을 흉내낸 경우 정규화.

    markdownify가 NBSP를 일반 공백으로 보존하면서 한 단락에 모든 항목이
    뭉쳐 나오는 케이스를 잡는다.
    """
    if not text:
        return text

    # NBSP(\xa0) 단독 시퀀스를 일반 공백으로
    text = text.replace("\xa0", " ")

    # 닫는 괄호/종결 부호 + bullet → 줄바꿈
    text = _CLOSING_BEFORE_BULLET_RE.sub("\n", text)

    # 다중 공백 + dash/bullet → 줄바꿈
    text = _MULTISPACE_BEFORE_BULLET_RE.sub("\n", text)

    # 단일 공백 + 안전한 bullet 글자(•/▪/○ 등) → 줄바꿈
    text = _SINGLE_SPACE_BEFORE_SAFE_BULLET_RE.sub("\n", text)

    # 단어 + 공백 없이 "- 라벨" 패턴 → 줄바꿈
    text = _INLINE_DASH_LABEL_RE.sub("\n", text)

    # 라인 끝/시작에 짝 안 맞는 ** 노이즈 제거 (강조 매칭이 깨진 잔재)
    text = _strip_dangling_strong_markers(text)

    # 한 단락에 뭉친 "가.", "1)" marker를 줄바꿈으로 분리
    text = _split_inline_markers(text)

    # 빈 줄 직후 4+ space 들여쓰기 라인이 accidental 코드 블록으로 인식되는 것 방지
    text = _strip_accidental_code_indent(text)

    return text


# Markdown spec: 빈 줄 또는 문서 시작 직후 4+ space 들여쓰기 라인은 indented code block.
# 원본 HTML이 &nbsp; 시퀀스로 가운데 정렬/들여쓰기를 흉내낸 라인(예: 푸터 "                **생 활 관**")
# 이 코드 블록으로 인식돼 검은 배경 + raw `**`로 보이는 부작용을 잡는다.
# list item 안의 continuation(앞 라인이 빈 줄 아님)은 영향 없음.
_ACCIDENTAL_CODE_INDENT_RE = re.compile(
    r"(\A|\n[ \t]*\n)([ \t]{4,})(\S)"
)


def _strip_accidental_code_indent(text: str) -> str:
    return _ACCIDENTAL_CODE_INDENT_RE.sub(lambda m: f"{m.group(1)}{m.group(3)}", text)


def _strip_dangling_strong_markers(text: str) -> str:
    """한 라인 안의 ``**`` 개수가 홀수면 마지막 dangling marker를 제거한다.

    원본 HTML에서 strong 태그가 라인을 넘어 닫히거나 markdownify가 짝을 맞추지
    못한 결과로 라인 끝/시작에 의미 없는 ``**`` 가 남는 경우를 정리한다.

    GFM 표 라인(``|`` 로 시작/끝)은 셀별로 검사한다. 잘못된 HTML이
    ``<td><strong>A</td><td>B</strong></td>`` 식으로 셀 경계를 가로지른 strong을
    만들면, markdownify는 ``| **A | B** |`` 같이 셀당 ``**`` 가 1개씩만 남는
    결과를 만든다. 라인 전체 개수로는 짝수(2)라 놓치므로 셀 단위로 잘라낸다.
    """
    lines: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            line = _strip_dangling_in_table_row(line)
        elif line.count("**") % 2 == 1:
            line = _drop_last_strong_marker(line)
        lines.append(line)
    return "\n".join(lines)


def _strip_dangling_in_table_row(line: str) -> str:
    cells = line.split("|")
    for i, cell in enumerate(cells):
        if cell.count("**") % 2 == 1:
            cells[i] = _drop_last_strong_marker(cell)
    return "|".join(cells)


def _drop_last_strong_marker(text: str) -> str:
    tail_idx = text.rfind("**")
    if tail_idx < 0:
        return text
    return (text[:tail_idx] + text[tail_idx + 2 :]).rstrip()


# 한국어 공지에서 흔한 항목 마커: "가.", "나.", "다.", "라.", "마.", "바.", "사."
# + 숫자) (1), 2), 3), …)
# marker가 텍스트 중간에 박혀 있으면(<br> 없이) 줄바꿈 없이 다 뭉친다.
# 직전이 종결 부호/괄호 닫힘/한글일 때 줄바꿈을 추가한다.
# 직전 문자에서 숫자는 제외한다. `(02) 970`, `(031) 1234` 같은 전화번호의
# 닫는 괄호를 `2) `/`1) ` 리스트 마커로 오인해 끊는 회귀를 막는다.
_NUMERIC_MARKER_RE = re.compile(
    r"(?<=[가-힣\)\]])(?=\d+\)\s+\S)"
)
_HANGUL_MARKER_RE = re.compile(
    r"(?<=[\.\)\]\d])(?=[가-사]\.\s+[가-힣A-Za-z])"
)


def _split_inline_markers(text: str) -> str:
    """한 단락에 뭉친 marker(`1) `, `가. `)를 줄바꿈으로 분리한다.

    한국어 marker만 잡고, dash/숫자/한글 어미 등 정상 표현을 보호하려고 직전
    문자를 제한한다.
    """
    text = _NUMERIC_MARKER_RE.sub("\n", text)
    text = _HANGUL_MARKER_RE.sub("\n", text)
    return text


def _escape_unbalanced_backticks(text: str) -> str:
    """Escape literal year abbreviations such as ``(`25)``.

    Korean notices often use a backtick as a visual apostrophe. A single
    backtick starts an inline code span in Markdown, so escape only lines with
    an odd number of unescaped backticks.
    """
    lines: list[str] = []
    for line in text.split("\n"):
        if _count_unescaped_backticks(line) % 2 == 1:
            line = line.replace("`", "\\`")
        lines.append(line)
    return "\n".join(lines)


def _count_unescaped_backticks(line: str) -> int:
    count = 0
    escaped = False
    for char in line:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "`":
            count += 1
    return count


def _normalize_emphasis(text: str) -> str:
    """markdownify 결과에서 의미 없는/깨질 강조 마크업을 정리한다.

    크롤링 원본 HTML에 ``<strong>-</strong>제출항목`` 같은 식으로 단일
    기호만 강조한 경우, markdownify는 ``**-**제출항목``을 만들어 시각적으로
    어색하고 CommonMark + 한국어 right-flanking rule도 깨진다.

    적용 순서:
    1. bullet 흉내(`**-**텍스트`, `**•**텍스트`)는 실제 `- 텍스트` 형태로
    2. 공백/구두점만 들어간 강조는 강조 마크 제거 (`****`, `**: **` 등)
    3. CJK 인접 강조는 강조 마크 제거 (어차피 렌더되지 않음)
    """
    if not text:
        return text

    # 1) bullet-impersonation을 진짜 dash 리스트 모양으로 풀어준다.
    text = _BULLET_LIKE_RE.sub(r"\1- ", text)

    # 2) decorative-only (공백/기호만) 강조 제거. 반복 적용해 중첩도 정리.
    previous = None
    while previous != text:
        previous = text
        text = _EMPHASIS_DECORATIVE_RE.sub(r"\2", text)

    # 3) CJK 인접 강조는 raw로 풀어준다.
    text = _CJK_LEFT_EMPHASIS_RE.sub(r"\2", text)
    text = _CJK_RIGHT_EMPHASIS_RE.sub(r"\2", text)

    return text


def _escape_alt(value: str) -> str:
    return value.replace("[", "\\[").replace("]", "\\]")
