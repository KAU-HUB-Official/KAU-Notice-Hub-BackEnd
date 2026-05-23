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


def _escape_alt(value: str) -> str:
    return value.replace("[", "\\[").replace("]", "\\]")
