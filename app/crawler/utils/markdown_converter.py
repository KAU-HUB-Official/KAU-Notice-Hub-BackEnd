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
        absolute = urljoin(base_url, src) if base_url else src
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

    if base_url:
        for tag_name, attr in _URL_ATTRS:
            for tag in soup.find_all(tag_name):
                value = (tag.get(attr) or "").strip()
                if not value or value.startswith(("javascript:", "mailto:", "tel:", "#")):
                    continue
                tag[attr] = urljoin(base_url, value)

    return soup.decode()


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

# 다중 공백 (2+) 다음에 bullet character + 공백/탭이 오면 줄바꿈으로 정규화.
# 예: "스토어:        • 이케아 고양점" → "스토어:\n• 이케아 고양점"
# 직전이 비공백이어야 줄 시작과 구분.
_MULTISPACE_BEFORE_BULLET_RE = re.compile(
    rf"(?<=\S)[ \t]{{2,}}(?=[{_INLINE_BULLET_CHARS}][ \t])"
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

    # 다중 공백 + bullet → 줄바꿈
    text = _MULTISPACE_BEFORE_BULLET_RE.sub("\n", text)

    # 단어 + 공백 없이 "- 라벨" 패턴 → 줄바꿈
    text = _INLINE_DASH_LABEL_RE.sub("\n", text)

    return text


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
