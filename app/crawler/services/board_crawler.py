from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..models.post import Post
from ..parsers.base_parser import BaseParser
from ..policies.notice_policy import evaluate_recent_policy
from ..services.url_normalizer import canonicalize_original_url
from ..utils.logger import get_logger

logger = get_logger("crawler.services.board_crawler")


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
        logger.warning("[%s] robots.txt 차단으로 상세 스킵: %s", board["name"], detail_url)
        return None, False

    fetch_result = adapter.fetch_detail(board, detail_url)
    if not fetch_result.html:
        if fetch_result.failure_reason == "missing_ntt_id":
            logger.warning("[%s] 상세 URL에 nttId 누락: %s", board["name"], detail_url)
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
        _fill_missing_content_from_attachments(post)
        if not post.title or not post.content:
            failed_items.append(
                {
                    "board": board["name"],
                    "url": detail_url,
                    "reason": "required_field_empty",
                }
            )
            logger.warning("[%s] 필수 필드 누락으로 스킵: %s", board["name"], detail_url)
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
        post_dict["is_permanent_notice"] = is_permanent_notice
        known_urls.add(post.original_url)
        known_posts_by_url[post.original_url] = post_dict
        return post_dict, False
    except Exception as exc:  # noqa: BLE001
        logger.exception("[%s] 상세 파싱 실패: %s", board["name"], detail_url)
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
            logger.warning("[%s] robots.txt 차단으로 목록 스킵: %s", board["name"], page_url)
            # robots가 전역 차단인 경우가 많으므로 페이지 루프를 조기 종료한다.
            break

        html = adapter.fetch_list_html(board, page)

        if not html:
            logger.error(
                "[%s] 목록 요청 실패: page=%s, url=%s",
                board["name"],
                page,
                page_url,
            )
            break

        page_items = _normalize_page_items(parser.parse_post_items(html, page_url), page=page)
        if not page_items:
            logger.info("[%s] 목록 항목 없음, page=%s에서 페이지 순회 종료", board["name"], page)
            break

        page_signature = tuple(str(item.get("url") or "") for item in page_items)
        if page_signature in seen_page_signatures:
            logger.info("[%s] 반복 목록 감지, page=%s에서 페이지 순회 종료", board["name"], page)
            break
        seen_page_signatures.add(page_signature)

        new_page_items = [
            item
            for item in page_items
            if str(item.get("url") or "") not in seen_for_board
        ]

        logger.info(
            "[%s] 목록 파싱 완료: page=%s, collected=%s, new=%s",
            board["name"],
            page,
            len(page_items),
            len(new_page_items),
        )

        permanent_items = [item for item in page_items if bool(item.get("is_permanent_notice"))]
        general_items = [item for item in page_items if not bool(item.get("is_permanent_notice"))]
        ordered_page_items = _dedup_items(permanent_items + general_items)

        logger.info(
            "[%s] page=%s 상세 대상: total=%s (permanent=%s, general=%s)",
            board["name"],
            page,
            len(ordered_page_items),
            len(permanent_items),
            len(general_items),
        )

        stop_board = False
        for idx, detail_item in enumerate(ordered_page_items, start=1):
            detail_url = str(detail_item["url"])

            if detail_url in seen_for_board:
                _sync_known_item_metadata(detail_item, known_posts_by_url=known_posts)
                if _evaluate_known_item_policy(board, detail_item, known_posts_by_url=known_posts):
                    logger.info(
                        "[%s] 기존 수집 일반공지의 최근성 기준 초과로 page=%s에서 보드 수집 중단: %s",
                        board["name"],
                        page,
                        detail_url,
                    )
                    stop_board = True
                    break
                continue

            logger.info(
                "[%s] 상세 수집 중 (page=%s, %s/%s): %s",
                board["name"],
                page,
                idx,
                len(ordered_page_items),
                detail_url,
            )

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
                    "[%s] 정책에 따라 page=%s에서 보드 수집 중단: %s",
                    board["name"],
                    page,
                    detail_url,
                )
                stop_board = True
                break

        if stop_board:
            break

        page += 1

    return posts, failed_items
