from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.crawler.utils.markdown_converter import html_node_to_markdown
from app.schemas import Notice, NoticeAttachment


RawNotice = dict[str, Any]

DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")
HTML_FRAGMENT_PATTERN = re.compile(
    r"</?(?:p|div|section|article|table|thead|tbody|tr|td|th|ul|ol|li|h[1-6]|img)\b",
    flags=re.IGNORECASE,
)
BR_TAG_PATTERN = re.compile(r"<br\s*/?>", flags=re.IGNORECASE)
STRONG_TAG_PATTERN = re.compile(
    r"<(?:strong|b)\b[^>]*>(.*?)</(?:strong|b)>",
    flags=re.IGNORECASE | re.DOTALL,
)
EM_TAG_PATTERN = re.compile(
    r"<(?:em|i)\b[^>]*>(.*?)</(?:em|i)>",
    flags=re.IGNORECASE | re.DOTALL,
)
MARKER_SPACING_RE = re.compile(r"([▪※○•])(?=\S)")
DECORATIVE_SECTION_RE = re.compile(
    r"(^|(?<=\S)\s+)-\s*((?:다\s*음)|(?:아\s*래))\s*-\s*"
)
# 앞 토큰이 `숫자.`(연도/소수)면 분리하지 않는다. `2026. 08. 예정`의 `08.`을
# 섹션 마커로 오인해 날짜를 끊던 버그를 막는다. 문장 종결(`합니다.`)이나 한글/`)`
# 뒤의 진짜 섹션 마커는 그대로 분리한다.
DOTTED_NUMBER_MARKER_RE = re.compile(
    r"(?<![0-9]\.)(?<=[가-힣A-Za-z\)\]\"”'\.])[ \t]+(?=\d{1,2}\.\s+[가-힣A-Za-z])"
)
# 공백 없이 앞 텍스트에 바로 붙은 번호 섹션 마커(`참조2. 강의`, `불가5.성적`,
# `(필독!!!)4. 수강`)를 줄바꿈으로 분리한다. 직전이 한글/닫는 괄호/종결 부호이고
# 뒤가 `N. 한글` 형태일 때만 적용해 날짜(2026.06)·소수·전화번호를 보호한다.
INLINE_NUMBER_SECTION_RE = re.compile(
    r"(?<=[가-힣\)\]！!?。])(?=\d{1,2}\.\s*[가-힣])"
)
# 한글 문장 종결(`바랍니다.`) 직후 공백 없이 붙은 번호 섹션 마커를 분리한다.
# 앞을 `한글+마침표`로 한정해 날짜(`2026.1.`)·시간과 구분한다.
# 예: `많은 신청 바랍니다.1. 장학개요` → `바랍니다.` / `1. 장학개요`
SENTENCE_END_NUMBER_MARKER_RE = re.compile(
    r"(?<=[가-힣]\.)(?=\d{1,2}\.\s*[가-힣])"
)
INLINE_NOTICE_MARKER_RE = re.compile(r"(?<=\S)[ \t]*(?=[▪※○•]\s*)")
PROFESSOR_LIST_DASH_RE = re.compile(r"(?<=전공주임교수)[ \t]+-[ \t]+")
INLINE_MAJOR_ITEM_DASH_RE = re.compile(
    r"(?<=\))[ \t]+-[ \t]+(?=[A-Za-z가-힣\- ]{1,30}전공\b)"
)
INLINE_SECTION_HEADING_RE = re.compile(
    r"(\d{1,2}\.\s+(?:제출절차|문의\s*사항|문의사항))[ \t]+(?=\S)"
)
EMAIL_MAILTO_RE = re.compile(
    r"\[([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\]"
    r"\(mailto:[^)]+\)",
    flags=re.IGNORECASE,
)
TABLE_SEPARATOR_CELL_RE = re.compile(r":?-{3,}:?")
# 흐름/공정 표를 식별하는 화살표 단독 셀(예: `→`). 직사각형 판정과 함께
# 진짜 데이터 표가 아닌 레이아웃 표를 걸러내는 데 쓴다.
FLOW_ARROW_CELL_RE = re.compile(r"[\s→➔⇒⟶↠↦➞➜]+")
IMAGE_BODY_FALLBACK = "**[이미지 본문]**\n\n원문 공지에서 이미지를 확인해주세요."
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]\n]*\]\(")
HTML_COMMENT_BLOCK_RE = re.compile(r"<!--.*?-->", flags=re.DOTALL)
HTML_COMMENT_MARKER_RE = re.compile(r"<!--|-->")
UNSAFE_MARKDOWN_LINK_RE = re.compile(
    r"!?\[[^\]\n]*\]\(\s*(?:javascript|data):[^\n)]*\)",
    flags=re.IGNORECASE,
)
EMPTY_MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(\s*\)")
UNCLOSED_MARKDOWN_LINK_DEST_RE = re.compile(
    r"(!?\[[^\]\n]*\]\((?:https?://|/)[^\s)\n]+)$",
    flags=re.MULTILINE,
)
UNCLOSED_MARKDOWN_TEXT_RE = re.compile(r"(?<!\\)(!?)\[([^\]\n]*)$")
NON_URL_MARKDOWN_LINK_RE = re.compile(
    r"(?<!\\)\[([^\]\n]+)\]\(((?!https?://|mailto:|tel:|#|/)[^)]+)\)",
    flags=re.IGNORECASE,
)


def _to_string_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    trimmed = value.strip()
    return trimmed if trimmed else None


def _to_string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        normalized = _to_string_value(value)
        return [normalized] if normalized else []

    if not isinstance(value, list):
        return []

    values: list[str] = []
    for item in value:
        normalized = _to_string_value(item)
        if normalized:
            values.append(normalized)
    return values


def _first_string(raw: RawNotice, keys: list[str]) -> str | None:
    for key in keys:
        value = _to_string_value(raw.get(key))
        if value:
            return value
    return None


def _first_string_list(raw: RawNotice, keys: list[str]) -> list[str]:
    for key in keys:
        values = _to_string_values(raw.get(key))
        if values:
            return values
    return []


def normalize_date(raw_value: Any) -> str | None:
    value = _to_string_value(raw_value)
    if not value:
        return None

    matched = DATE_PATTERN.search(value)
    if matched:
        return matched.group(1)

    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date().isoformat()
    except ValueError:
        return None


def strip_html(input_value: str) -> str:
    without_scripts = re.sub(
        r"<script[^>]*>[\s\S]*?</script>",
        "",
        input_value,
        flags=re.IGNORECASE,
    )
    without_styles = re.sub(
        r"<style[^>]*>[\s\S]*?</style>",
        "",
        without_scripts,
        flags=re.IGNORECASE,
    )
    without_tags = re.sub(r"<[^>]+>", " ", without_styles)
    return re.sub(r"\s+", " ", without_tags).strip()


def normalize_content_markdown(content: str) -> str:
    value = content.strip()
    if not value:
        return ""

    if HTML_FRAGMENT_PATTERN.search(value):
        markdown = html_node_to_markdown(value)
        if markdown:
            normalized = _normalize_markdown_structure(markdown)
            if normalized:
                return normalized
        if "<img" in value.lower():
            return IMAGE_BODY_FALLBACK
        return _normalize_markdown_structure(strip_html(value) or value)

    normalized = _normalize_markdown_structure(value)
    if normalized:
        return normalized
    if MARKDOWN_IMAGE_RE.search(value):
        return IMAGE_BODY_FALLBACK
    return normalized


def _normalize_markdown_structure(content: str) -> str:
    value = _normalize_inline_html_in_markdown(content)
    value = EMAIL_MAILTO_RE.sub(lambda m: f"[{m.group(1)}](mailto:{m.group(1)})", value)
    value = _normalize_flow_tables(value)
    value = _normalize_orphan_table_rows(value)
    lines: list[str] = []
    for line in value.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            lines.append(line)
            continue

        normalized = DECORATIVE_SECTION_RE.sub(
            _format_decorative_section,
            line,
        )
        normalized = DOTTED_NUMBER_MARKER_RE.sub("\n", normalized)
        normalized = INLINE_NUMBER_SECTION_RE.sub("\n", normalized)
        normalized = SENTENCE_END_NUMBER_MARKER_RE.sub("\n", normalized)
        normalized = INLINE_NOTICE_MARKER_RE.sub("\n", normalized)
        normalized = PROFESSOR_LIST_DASH_RE.sub("\n- ", normalized)
        normalized = INLINE_MAJOR_ITEM_DASH_RE.sub("\n- ", normalized)
        normalized = INLINE_SECTION_HEADING_RE.sub(r"\1\n", normalized)
        normalized = MARKER_SPACING_RE.sub(r"\1 ", normalized)
        lines.extend(part.rstrip() for part in normalized.splitlines())

    value = "\n".join(lines)
    value = _normalize_flow_tables(value)
    value = _normalize_orphan_table_rows(value)
    value = _repair_markdown_syntax(value)
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def _repair_markdown_syntax(content: str) -> str:
    value = HTML_COMMENT_BLOCK_RE.sub("", content)
    value = HTML_COMMENT_MARKER_RE.sub("", value)
    value = UNSAFE_MARKDOWN_LINK_RE.sub("", value)
    value = EMPTY_MARKDOWN_LINK_RE.sub("", value)
    value = UNCLOSED_MARKDOWN_LINK_DEST_RE.sub(r"\1)", value)
    value = NON_URL_MARKDOWN_LINK_RE.sub(r"\\[\1](\2)", value)
    value = _escape_unclosed_markdown_text(value)
    value = _escape_unbalanced_backticks(value)
    return value


def _escape_unclosed_markdown_text(content: str) -> str:
    lines: list[str] = []
    for line in content.splitlines():
        lines.append(UNCLOSED_MARKDOWN_TEXT_RE.sub(r"\1\\[\2", line))
    return "\n".join(lines)


def _escape_unbalanced_backticks(content: str) -> str:
    lines: list[str] = []
    for line in content.splitlines():
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


def _normalize_flow_tables(content: str) -> str:
    lines = content.splitlines()
    normalized: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if (
            _is_empty_table_row(line)
            and index + 1 < len(lines)
            and _is_table_separator_row(lines[index + 1])
        ):
            separator = lines[index + 1]
            data_index = index + 2
            data_rows: list[str] = []
            while data_index < len(lines) and _is_table_row(lines[data_index]):
                data_rows.append(lines[data_index])
                data_index += 1

            if _is_rectangular_data_table(separator, data_rows):
                # 첫 데이터 행을 헤더로 승격해 진짜 마크다운 표로 유지한다.
                normalized.append(data_rows[0])
                normalized.append(separator)
                normalized.extend(data_rows[1:])
            else:
                for row in data_rows:
                    text = _table_row_to_plain_text(row)
                    if text:
                        normalized.append(text)

            index = data_index
            continue
        normalized.append(line)
        index += 1
    return "\n".join(normalized)


def _is_rectangular_data_table(separator: str, data_rows: list[str]) -> bool:
    """빈 헤더 표가 '진짜 데이터 표'인지 판정한다.

    원본 HTML이 헤더 행을 ``<th>``가 아닌 ``<td>``로 만들면 markdownify는 빈
    헤더 + 구분선을 생성하고 실제 헤더는 첫 데이터 행이 된다. 이런 표 중
    아래 조건을 모두 만족하면 첫 행을 헤더로 승격해 표로 유지한다.

    - 구분선 기준 3열 이상
    - 헤더 후보 1행 + 본문 1행 이상(데이터 행 2개 이상)
    - 모든 행의 칸 수가 동일한 직사각형
    - 화살표 단독 셀(흐름/공정 표)이 없음

    조건을 벗어나는 레이아웃/흐름 표는 기존대로 평문화한다.
    """
    ncols = len(_table_cells(separator))
    if ncols < 3 or len(data_rows) < 2:
        return False
    for row in data_rows:
        cells = _table_cells(row)
        if len(cells) != ncols:
            return False
        if any(cell and FLOW_ARROW_CELL_RE.fullmatch(cell) for cell in cells):
            return False
    return True


def _normalize_orphan_table_rows(content: str) -> str:
    lines = content.splitlines()
    normalized: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not _is_table_row(line):
            normalized.append(line)
            index += 1
            continue

        if index + 1 < len(lines) and _is_table_separator_row(lines[index + 1]):
            normalized.append(line)
            index += 1
            while index < len(lines) and _is_table_row(lines[index]):
                normalized.append(lines[index])
                index += 1
            continue

        normalized.append(_table_row_to_plain_text(line))
        index += 1

    return "\n".join(normalized)


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_empty_table_row(line: str) -> bool:
    cells = _table_cells(line)
    return bool(cells) and all(not cell for cell in cells)


def _is_table_separator_row(line: str) -> bool:
    if not _is_table_row(line):
        return False
    cells = _table_cells(line)
    return bool(cells) and all(TABLE_SEPARATOR_CELL_RE.fullmatch(cell) for cell in cells)


def _table_row_to_plain_text(line: str) -> str:
    cells = [
        cell
        for cell in _table_cells(line)
        if cell and not TABLE_SEPARATOR_CELL_RE.fullmatch(cell)
    ]
    return " ".join(cells)


def _format_decorative_section(match: re.Match[str]) -> str:
    prefix = "\n\n" if match.group(1) else ""
    label = match.group(2).replace(" ", "")
    return f"{prefix}{label}\n\n"


def _normalize_inline_html_in_markdown(content: str) -> str:
    lines: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            lines.append(BR_TAG_PATTERN.sub(" / ", line))
        else:
            lines.append(BR_TAG_PATTERN.sub("\n", line))

    value = "\n".join(lines)
    value = STRONG_TAG_PATTERN.sub(lambda m: f"**{m.group(1).strip()}**", value)
    value = EM_TAG_PATTERN.sub(lambda m: f"*{m.group(1).strip()}*", value)
    return value.strip()


def make_summary(content: str, fallback: str | None = None) -> str:
    if fallback and fallback.strip():
        return fallback.strip()

    plain = strip_html(content)
    return plain if len(plain) <= 180 else f"{plain[:180]}..."


def slugify(input_value: str) -> str:
    lowered = input_value.lower()
    slug = re.sub(r"[^a-z0-9가-힣]+", "-", lowered)
    slug = re.sub(r"^-+|-+$", "", slug)[:48]
    return slug or "notice"


def normalize_attachments(raw_value: Any) -> list[NoticeAttachment]:
    if not isinstance(raw_value, list):
        return []

    attachments: list[NoticeAttachment] = []
    for item in raw_value:
        if isinstance(item, str):
            url = item.strip()
            if url:
                attachments.append(NoticeAttachment(name="첨부파일", url=url))
            continue

        if isinstance(item, dict):
            url = (
                _to_string_value(item.get("url"))
                or _to_string_value(item.get("href"))
                or _to_string_value(item.get("link"))
            )
            if not url:
                continue

            name = (
                _to_string_value(item.get("name"))
                or _to_string_value(item.get("filename"))
                or _to_string_value(item.get("title"))
                or "첨부파일"
            )
            attachments.append(NoticeAttachment(name=name, url=url))

    return attachments


def normalize_tags(raw: RawNotice, sources: list[str], categories: list[str]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        trimmed = value.strip()
        if trimmed and trimmed not in seen:
            seen.add(trimmed)
            tags.append(trimmed)

    raw_tags = raw.get("tags")
    if isinstance(raw_tags, list):
        for value in raw_tags:
            if isinstance(value, str):
                add(value)

    for category in categories:
        add(category)

    for source in sources:
        add(source)

    return tags


def normalize_notice(raw: RawNotice, index: int) -> Notice:
    title = _first_string(raw, ["title", "subject", "name"]) or f"제목 없음 공지 {index + 1}"
    raw_content = (
        _first_string(raw, ["content", "body", "text", "description"])
        or "본문 정보가 비어 있습니다."
    )
    content = normalize_content_markdown(raw_content)

    sources = _first_string_list(raw, ["source", "source_name", "source_type", "board"])
    source = sources[0] if sources else None
    categories = _first_string_list(raw, ["category", "category_raw", "type"])
    category = categories[0] if categories else None
    department = _first_string(raw, ["department", "department_name", "office"])
    url = _first_string(raw, ["url", "original_url", "link", "href"])
    date = normalize_date(
        raw.get("date")
        or raw.get("published_at")
        or raw.get("created_at")
        or raw.get("updated_at")
    )

    fallback_id_seed = f"{title}-{date or ''}-{source or ''}-{index + 1}"
    notice_id = _first_string(raw, ["id", "notice_id", "post_id", "uuid"]) or slugify(
        fallback_id_seed
    )
    summary = make_summary(
        content,
        _first_string(raw, ["summary", "excerpt", "short_description"]),
    )

    return Notice(
        id=notice_id,
        title=title,
        content=content,
        url=url,
        source=source,
        sources=sources,
        category=category,
        department=department,
        date=date,
        summary=summary,
        tags=normalize_tags(raw, sources, categories),
        attachments=normalize_attachments(raw.get("attachments")),
    )
