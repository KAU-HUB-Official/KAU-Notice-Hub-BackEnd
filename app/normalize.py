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
MARKER_SPACING_RE = re.compile(r"([▪※])(?=\S)")
DECORATIVE_SECTION_RE = re.compile(
    r"(^|(?<=\S)\s+)-\s*((?:다\s*음)|(?:아\s*래))\s*-\s*"
)
DOTTED_NUMBER_MARKER_RE = re.compile(
    r"(?<=[가-힣A-Za-z\)\]\"”'\.])[ \t]+(?=\d{1,2}\.\s+[가-힣A-Za-z])"
)
INLINE_NOTICE_MARKER_RE = re.compile(r"(?<=\S)[ \t]+(?=[▪※]\s*)")
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
            return _normalize_markdown_structure(markdown)
        if "<img" in value.lower():
            return "**[이미지 본문]**\n\n원문 공지에서 이미지를 확인해주세요."
        return _normalize_markdown_structure(strip_html(value) or value)

    return _normalize_markdown_structure(value)


def _normalize_markdown_structure(content: str) -> str:
    value = _normalize_inline_html_in_markdown(content)
    value = EMAIL_MAILTO_RE.sub(lambda m: f"[{m.group(1)}](mailto:{m.group(1)})", value)
    value = _normalize_flow_tables(value)
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
        normalized = INLINE_NOTICE_MARKER_RE.sub("\n", normalized)
        normalized = PROFESSOR_LIST_DASH_RE.sub("\n- ", normalized)
        normalized = INLINE_MAJOR_ITEM_DASH_RE.sub("\n- ", normalized)
        normalized = INLINE_SECTION_HEADING_RE.sub(r"\1\n", normalized)
        normalized = MARKER_SPACING_RE.sub(r"\1 ", normalized)
        lines.extend(part.rstrip() for part in normalized.splitlines())

    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


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
            index += 2
            while index < len(lines) and _is_table_row(lines[index]):
                text = _table_row_to_plain_text(lines[index])
                if text:
                    normalized.append(text)
                index += 1
            continue
        normalized.append(line)
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
    cells = _table_cells(line)
    return bool(cells) and all(TABLE_SEPARATOR_CELL_RE.fullmatch(cell) for cell in cells)


def _table_row_to_plain_text(line: str) -> str:
    cells = [cell for cell in _table_cells(line) if cell]
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
