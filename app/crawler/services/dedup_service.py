from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from ..policies.notice_policy import should_prune_stale_notice
from ..services.url_normalizer import canonicalize_original_url
from ..utils.logger import get_logger

logger = get_logger("crawler.services.dedup_service")

METADATA_ARRAY_FIELDS: tuple[str, ...] = (
    "source_name",
    "source_type",
    "category_raw",
)


@dataclass(frozen=True)
class MergeResult:
    posts: list[dict]
    url_dedup_removed: int
    title_dedup_removed: int


@dataclass(frozen=True)
class RetentionPruneResult:
    posts: list[dict]
    stale_pruned: int


def normalize_title_for_dedup(title: str | None) -> str:
    if not title:
        return ""

    # 사이트별 공백/대소문자 차이를 줄여 제목 기반 중복 판단 키를 만든다.
    normalized = re.sub(r"\s+", " ", str(title)).strip().lower()
    return normalized


def _ensure_list(value: object) -> list:
    if isinstance(value, list):
        return [item for item in value if item not in (None, "")]
    if value in (None, ""):
        return []
    return [value]


def _merge_unique_values(base_values: list, incoming_values: list) -> list:
    merged = list(base_values)
    for value in incoming_values:
        if value in merged:
            continue
        merged.append(value)
    return merged


def _build_source_meta_entry(post: dict) -> dict:
    return {
        "source_name": post.get("source_name"),
        "source_type": post.get("source_type"),
        "category_raw": post.get("category_raw"),
        "original_url": post.get("original_url"),
        "published_at": post.get("published_at"),
        "crawled_at": post.get("crawled_at"),
        "is_permanent_notice": bool(post.get("is_permanent_notice")),
    }


def _to_hashable(value: object) -> object:
    if isinstance(value, list):
        return tuple(_to_hashable(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((str(key), _to_hashable(item)) for key, item in value.items()))
    return value


def _meta_entry_key(entry: dict) -> tuple:
    return (
        _to_hashable(entry.get("source_name")),
        _to_hashable(entry.get("source_type")),
        _to_hashable(entry.get("category_raw")),
        _to_hashable(entry.get("original_url")),
    )


def _merge_attachments(existing_post: dict, incoming_post: dict) -> None:
    existing_raw = existing_post.get("attachments")
    incoming_raw = incoming_post.get("attachments")

    existing_attachments = list(existing_raw) if isinstance(existing_raw, list) else []
    incoming_attachments = list(incoming_raw) if isinstance(incoming_raw, list) else []

    seen_urls: set[str] = {
        str(item.get("url") or "")
        for item in existing_attachments
        if isinstance(item, dict) and item.get("url")
    }
    merged = list(existing_attachments)

    for item in incoming_attachments:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        merged.append(item)

    existing_post["attachments"] = merged


def _merge_title_duplicate(existing_post: dict, duplicate_post: dict) -> None:
    # 제목 중복으로 통합되는 공지의 출처 메타를 별도 배열로 누적한다.
    source_meta = existing_post.get("source_meta")
    source_meta_list = list(source_meta) if isinstance(source_meta, list) else []

    if not source_meta_list:
        source_meta_list.append(_build_source_meta_entry(existing_post))

    seen_meta_keys = {_meta_entry_key(entry) for entry in source_meta_list if isinstance(entry, dict)}
    incoming_entry = _build_source_meta_entry(duplicate_post)
    incoming_key = _meta_entry_key(incoming_entry)
    if incoming_key not in seen_meta_keys:
        source_meta_list.append(incoming_entry)

    # source_name/source_type/category_raw를 배열로 병합한다.
    for field in METADATA_ARRAY_FIELDS:
        merged = _merge_unique_values(
            _ensure_list(existing_post.get(field)),
            _ensure_list(duplicate_post.get(field)),
        )
        existing_post[field] = merged

    existing_post["is_permanent_notice"] = bool(
        existing_post.get("is_permanent_notice")
        or duplicate_post.get("is_permanent_notice")
    )
    existing_post["source_meta"] = source_meta_list
    _merge_attachments(existing_post, duplicate_post)


def merge_posts_with_dedup(existing_posts: list[dict], new_posts: list[dict]) -> MergeResult:
    url_dedup_posts: list[dict] = []
    seen_url_to_index: dict[str, int] = {}

    # 기존 보유 데이터를 먼저 유지하고, 신규 데이터를 뒤에 병합한다.
    for post in existing_posts + new_posts:
        original_url = canonicalize_original_url(str(post.get("original_url") or ""))
        if not original_url:
            continue
        if original_url in seen_url_to_index:
            existing_post = url_dedup_posts[seen_url_to_index[original_url]]
            if post.get("is_permanent_notice"):
                existing_post["is_permanent_notice"] = True
            continue
        copied = dict(post)
        copied["original_url"] = original_url
        seen_url_to_index[original_url] = len(url_dedup_posts)
        url_dedup_posts.append(copied)

    dedup_posts: list[dict] = []
    title_to_index: dict[str, int] = {}
    title_dedup_removed = 0

    # 제목이 동일한 공지는 1건으로 통합하고, 출처 메타는 배열로 누적한다.
    for post in url_dedup_posts:
        title_key = normalize_title_for_dedup(str(post.get("title") or ""))
        if title_key and title_key in title_to_index:
            title_dedup_removed += 1
            existing_post = dedup_posts[title_to_index[title_key]]
            _merge_title_duplicate(existing_post, post)
            logger.info(
                "제목 중복으로 메타 병합: title=%s, url=%s",
                post.get("title"),
                post.get("original_url"),
            )
            continue

        dedup_posts.append(post)
        if title_key:
            title_to_index[title_key] = len(dedup_posts) - 1

    url_dedup_removed = len(existing_posts) + len(new_posts) - len(url_dedup_posts)
    return MergeResult(
        posts=dedup_posts,
        url_dedup_removed=url_dedup_removed,
        title_dedup_removed=title_dedup_removed,
    )


def prune_stale_posts(
    posts: list[dict],
    *,
    current_date: date | None = None,
) -> RetentionPruneResult:
    kept_posts: list[dict] = []
    stale_pruned = 0

    for post in posts:
        if should_prune_stale_notice(post, current_date=current_date):
            stale_pruned += 1
            logger.debug(
                "1년 이상 지난 일반공지 삭제: title=%s, published_at=%s, url=%s",
                post.get("title"),
                post.get("published_at"),
                post.get("original_url"),
            )
            continue
        kept_posts.append(post)

    return RetentionPruneResult(posts=kept_posts, stale_pruned=stale_pruned)
