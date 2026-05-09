from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..models.post import Post
from ..parsers.base_parser import BaseParser
from ..policies.notice_policy import evaluate_recent_policy
from ..services.content_asset_downloader import (
    extract_inline_embed_assets,
    extract_inline_image_assets,
)
from ..services.url_normalizer import canonicalize_original_url
from ..utils.logger import get_logger

logger = get_logger("crawler.services.board_crawler")


def _board_label(board: dict[str, Any]) -> str:
    name = str(board.get("name") or board.get("key") or "").strip()
    return name.removesuffix("공지사항").strip() or name


@dataclass(frozen=True)
class DetailFetchResult:
    html: str | None
    failure_reason: str = "request_failed"


@dataclass(frozen=True)
class BoardAdapter:
    parser_factory: Callable[[dict[str, Any]], BaseParser]
    build_list_page_url: Callable[[dict[str, Any], int], str]
    fetch_list_html: Callable[[dict[str, Any], int], str | None]
    fetch_detail: Callable[[dict[str, Any], str], DetailFetchResult]
    can_fetch: Callable[[str], bool] | None = None
    check_robots_on_list: bool = False
    check_robots_on_detail: bool = False
    min_pages_field: str | None = None


def _normalize_page_items(raw_items: list[dict], *, page: int) -> list[dict]:
    normalized_items: list[dict] = []

    for raw in raw_items:
        detail_url = canonicalize_original_url(str(raw.get("url") or ""))
        if not detail_url:
            continue
        normalized_items.append(
            {
                "url": detail_url,
                "page": page,
                "is_permanent_notice": bool(raw.get("is_permanent_notice")),
            }
        )

    return normalized_items


def _dedup_items(items: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen_urls: set[str] = set()

    for item in items:
        detail_url = str(item.get("url") or "")
        if not detail_url or detail_url in seen_urls:
            continue
        seen_urls.add(detail_url)
        deduped.append(item)

    return deduped


def _resolve_page_limit(
    board: dict[str, Any],
    *,
    max_pages: int,
    adapter: BoardAdapter,
) -> int | None:
    if max_pages <= 0:
        return None

    page_limit = max_pages
    if adapter.min_pages_field:
        min_pages = max(1, int(board.get(adapter.min_pages_field, 1)))
        page_limit = max(page_limit, min_pages)
    return page_limit


def _fill_missing_content_from_attachments(post: Post) -> None:
    if post.content or not post.attachments:
        return

    labels: list[str] = []
    seen_labels: set[str] = set()

    for attachment in post.attachments:
        if not isinstance(attachment, dict):
            continue

        label = str(attachment.get("name") or attachment.get("url") or "").strip()
        if not label or label in seen_labels:
            continue

        seen_labels.add(label)
        labels.append(label)

    if labels:
        post.content = "[첨부파일 공지]\n" + "\n".join(f"- {label}" for label in labels)


def _asset_labels(assets: list[dict]) -> list[str]:
    labels: list[str] = []
    seen_labels: set[str] = set()

    for asset in assets:
        if not isinstance(asset, dict):
            continue

        label = str(asset.get("name") or asset.get("url") or "").strip()
        if not label or label in seen_labels:
            continue

        seen_labels.add(label)
        labels.append(label)

    return labels


def _fill_missing_content_from_body_assets(
    post: Post,
    *,
    inline_images: list[dict],
    inline_embeds: list[dict],
) -> None:
    if post.content:
        return

    if inline_images:
        lines = [f"[이미지 본문] 텍스트 본문 없음 (이미지 {len(inline_images)}개)"]
        lines.extend(f"- {label}" for label in _asset_labels(inline_images))
        post.content = "\n".join(lines)
        return

    if inline_embeds:
        lines = [f"[동영상 본문] 텍스트 본문 없음 (동영상 {len(inline_embeds)}개)"]
        lines.extend(f"- {label}" for label in _asset_labels(inline_embeds))
        post.content = "\n".join(lines)


def _missing_required_fields(post: Post) -> list[str]:
    missing_fields: list[str] = []
    if not str(post.title or "").strip():
        missing_fields.append("title")
    if not str(post.content or "").strip():
        missing_fields.append("content")
    return missing_fields


def _required_field_failure_reason(missing_fields: list[str]) -> str:
    if not missing_fields:
        return "required_field_empty"
    return f"required_field_empty:{','.join(missing_fields)}"


def _evaluate_known_item_policy(
    board: dict[str, Any],
    detail_item: dict,
    *,
    known_posts_by_url: dict[str, dict],
) -> bool:
    if bool(detail_item.get("is_permanent_notice")):
        return False

    detail_url = str(detail_item.get("url") or "")
    known_post = known_posts_by_url.get(detail_url)
    if not known_post:
        return False

    decision = evaluate_recent_policy(
        board_name=board["name"],
        detail_url=detail_url,
        source_page=int(detail_item.get("page") or 1),
        is_permanent_notice=False,
        published_at=str(known_post.get("published_at") or ""),
    )
    return decision.stop_crawling


def _sync_known_item_metadata(
    detail_item: dict,
    *,
    known_posts_by_url: dict[str, dict],
) -> None:
    detail_url = str(detail_item.get("url") or "")
    known_post = known_posts_by_url.get(detail_url)
    if not known_post:
        return

    known_post["is_permanent_notice"] = bool(detail_item.get("is_permanent_notice"))


def _parse_detail_item(
    board: dict[str, Any],
    detail_item: dict,
    *,
    adapter: BoardAdapter,
    parser: BaseParser,
    known_urls: set[str],
    known_posts_by_url: dict[str, dict],
    failed_items: list[dict],
) -> tuple[dict | None, bool]:
    board_label = _board_label(board)
    detail_url = str(detail_item["url"])
    source_page = int(detail_item["page"])
    is_permanent_notice = bool(detail_item["is_permanent_notice"])

    if (
        adapter.check_robots_on_detail
        and adapter.can_fetch is not None
        and not adapter.can_fetch(detail_url)
    ):
        failed_items.append(
            {
                "board": board["name"],
                "url": detail_url,
                "reason": "robots_disallowed",
            }
        )
        logger.warning("상세 스킵 | 게시판=%s | 사유=robots 차단 | url=%s", board_label, detail_url)
        return None, False

    fetch_result = adapter.fetch_detail(board, detail_url)
    if not fetch_result.html:
        if fetch_result.failure_reason == "missing_ntt_id":
            logger.warning("상세 스킵 | 게시판=%s | 사유=nttId 누락 | url=%s", board_label, detail_url)
        failed_items.append(
            {
                "board": board["name"],
                "url": detail_url,
                "reason": fetch_result.failure_reason,
            }
        )
        return None, False

    try:
        post = parser.parse_post(fetch_result.html, detail_url)
        post.original_url = canonicalize_original_url(post.original_url)
        inline_assets = extract_inline_image_assets(fetch_result.html, detail_url)
        inline_embeds = extract_inline_embed_assets(fetch_result.html, detail_url)
        _fill_missing_content_from_body_assets(
            post,
            inline_images=inline_assets,
            inline_embeds=inline_embeds,
        )
        _fill_missing_content_from_attachments(post)
        missing_fields = _missing_required_fields(post)
        if missing_fields:
            failed_items.append(
                {
                    "board": board["name"],
                    "url": detail_url,
                    "reason": _required_field_failure_reason(missing_fields),
                    "missing_fields": missing_fields,
                }
            )
            logger.warning(
                "상세 스킵 | 게시판=%s | 사유=필수 필드 누락 | 필드=%s | url=%s",
                board_label,
                ",".join(missing_fields),
                detail_url,
            )
            return None, False

        decision = evaluate_recent_policy(
            board_name=board["name"],
            detail_url=detail_url,
            source_page=source_page,
            is_permanent_notice=is_permanent_notice,
            published_at=post.published_at,
        )
        if not decision.include_post:
            return None, decision.stop_crawling

        post_dict = post.to_dict()
        if inline_assets:
            post_dict["content_assets"] = inline_assets
        post_dict["is_permanent_notice"] = is_permanent_notice
        known_urls.add(post.original_url)
        known_posts_by_url[post.original_url] = post_dict
        return post_dict, False
    except Exception as exc:  # noqa: BLE001
        logger.exception("상세 실패 | 게시판=%s | 사유=파싱 오류 | url=%s", board_label, detail_url)
        failed_items.append(
            {
                "board": board["name"],
                "url": detail_url,
                "reason": f"parse_error:{exc.__class__.__name__}",
            }
        )
        return None, False


def crawl_board(
    board: dict[str, Any],
    *,
    max_pages: int,
    adapter: BoardAdapter,
    known_urls: set[str],
    known_posts_by_url: dict[str, dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    parser = adapter.parser_factory(board)
    board_label = _board_label(board)

    failed_items: list[dict] = []
    posts: list[dict] = []
    known_posts = known_posts_by_url if known_posts_by_url is not None else {}
    seen_for_board: set[str] = set(known_urls)
    seen_page_signatures: set[tuple[str, ...]] = set()
    page_limit = _resolve_page_limit(board, max_pages=max_pages, adapter=adapter)

    page = 1
    while page_limit is None or page <= page_limit:
        page_url = adapter.build_list_page_url(board, page)

        if (
            adapter.check_robots_on_list
            and adapter.can_fetch is not None
            and not adapter.can_fetch(page_url)
        ):
            failed_items.append(
                {
                    "board": board["name"],
                    "url": page_url,
                    "reason": "robots_disallowed",
                }
            )
            logger.warning("수집 종료 | 게시판=%s | 사유=robots 차단 | 페이지=%s", board_label, page)
            # robots가 전역 차단인 경우가 많으므로 페이지 루프를 조기 종료한다.
            break

        html = adapter.fetch_list_html(board, page)

        if not html:
            logger.error(
                "수집 종료 | 게시판=%s | 사유=목록 요청 실패 | 페이지=%s | url=%s",
                board_label,
                page,
                page_url,
            )
            break

        page_items = _normalize_page_items(parser.parse_post_items(html, page_url), page=page)
        if not page_items:
            logger.info("수집 종료 | 게시판=%s | 사유=목록 없음 | 페이지=%s", board_label, page)
            break

        page_signature = tuple(str(item.get("url") or "") for item in page_items)
        if page_signature in seen_page_signatures:
            logger.info("수집 종료 | 게시판=%s | 사유=반복 목록 | 페이지=%s", board_label, page)
            break
        seen_page_signatures.add(page_signature)

        new_page_items = [
            item
            for item in page_items
            if str(item.get("url") or "") not in seen_for_board
        ]

        permanent_items = [
            item for item in page_items if bool(item.get("is_permanent_notice"))
        ]
        general_items = [
            item for item in page_items if not bool(item.get("is_permanent_notice"))
        ]
        new_general_count = sum(
            1 for item in general_items if str(item.get("url") or "") not in seen_for_board
        )
        stop_after_page = bool(general_items) and new_general_count == 0
        ordered_page_items = _dedup_items(
            permanent_items if stop_after_page else permanent_items + general_items
        )

        logger.info(
            (
                "목록 | 게시판=%s | 페이지=%s | 전체=%s | 신규=%s "
                "| 상시공지=%s | 일반공지=%s | 신규일반공지=%s"
            ),
            board_label,
            page,
            len(page_items),
            len(new_page_items),
            len(permanent_items),
            len(general_items),
            new_general_count,
        )

        stop_board = False
        for detail_item in ordered_page_items:
            detail_url = str(detail_item["url"])

            if detail_url in seen_for_board:
                _sync_known_item_metadata(detail_item, known_posts_by_url=known_posts)
                if _evaluate_known_item_policy(board, detail_item, known_posts_by_url=known_posts):
                    logger.info(
                        "수집 종료 | 게시판=%s | 사유=기존 일반공지 1년 초과 | 페이지=%s | url=%s",
                        board_label,
                        page,
                        detail_url,
                    )
                    stop_board = True
                    break
                continue

            seen_for_board.add(detail_url)
            post, should_stop = _parse_detail_item(
                board,
                detail_item,
                adapter=adapter,
                parser=parser,
                known_urls=known_urls,
                known_posts_by_url=known_posts,
                failed_items=failed_items,
            )
            if post:
                posts.append(post)
            if should_stop:
                logger.info(
                    (
                        "수집 종료 | 게시판=%s "
                        "| 사유=일반공지 1년 초과 "
                        "| 페이지=%s | url=%s"
                    ),
                    board_label,
                    page,
                    detail_url,
                )
                stop_board = True
                break

        if stop_board or stop_after_page:
            if stop_after_page and not stop_board:
                logger.info(
                    "수집 종료 | 게시판=%s | 사유=신규 일반공지 없음 | 페이지=%s",
                    board_label,
                    page,
                )
            break

        page += 1

    return posts, failed_items
