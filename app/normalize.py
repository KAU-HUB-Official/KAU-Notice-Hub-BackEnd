from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.schemas import Notice, NoticeAttachment


RawNotice = dict[str, Any]

DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")


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
    content = (
        _first_string(raw, ["content", "body", "text", "description"])
        or "본문 정보가 비어 있습니다."
    )

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

