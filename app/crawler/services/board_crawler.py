from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Callable

from ..models.post import Post
from ..parsers.base_parser import BaseParser
from ..policies.notice_policy import (
    evaluate_recent_policy,
    parse_published_date,
    recent_stop_reason,
)
from ..services.content_asset_downloader import (
    extract_inline_embed_assets,
    extract_inline_image_assets,
)
from ..services.url_normalizer import canonicalize_original_url
from ..utils.logger import get_logger

logger = get_logger("crawler.services.board_crawler")

# 게시판 수집 중단 사유 (BoardCrawlReport.stop_reason)
STOP_SINCE_REACHED = "since_reached"  # 기간 경계(since 또는 RECENT_NOTICE_DAYS)를 넘은 일반공지에 도달
STOP_EMPTY_LIST = "empty_list"  # 목록 페이지에 공지가 없음
STOP_REPEATED_LIST = "repeated_list"  # 앞에서 본 목록이 그대로 되풀이됨
STOP_REQUEST_FAILED = "request_failed"  # 목록 페이지 요청 실패
STOP_ROBOTS_DISALLOWED = "robots_disallowed"
STOP_NO_NEW_ITEMS = "no_new_items"  # 목록의 일반공지가 모두 이미 아는 URL
STOP_PAGE_LIMIT = "page_limit"  # --max-pages 상한 도달


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


@dataclass
class BoardCrawlReport:
    """게시판 하나의 수집 기록.

    날짜가 아닌 이유(빈 목록, 반복 목록, 요청 실패)로 멈춘 게시판을 사람이 가려내는 데 쓴다.
    게시일 범위는 상시공지를 뺀 일반공지 기준이다. 상시공지는 오래돼도 수집하므로 기간 확보
    여부를 가리지 못한다.
    """

    board_key: str
    list_url: str
    pages_read: int = 0
    posts: int = 0
    permanent_posts: int = 0
    oldest_published_at: str | None = None
    newest_published_at: str | None = None
    stop_reason: str = STOP_PAGE_LIMIT
    stop_page: int | None = None
    failed_items: int = 0
    # 실패한 상세 항목(url/page/is_permanent_notice/reason). 재시도용이라 기록에는 싣지 않는다.
    failed_details: list[dict] = field(default_factory=list, repr=False)

    @property
    def reached_since(self) -> bool:
        return self.stop_reason == STOP_SINCE_REACHED

    def update_from_posts(self, posts: list[dict]) -> None:
        general_dates = sorted(
            published
            for post in posts
            if not post.get("is_permanent_notice")
            if (published := parse_published_date(post.get("published_at")))
        )
        self.posts = len(posts)
        self.permanent_posts = sum(1 for post in posts if post.get("is_permanent_notice"))
        self.oldest_published_at = general_dates[0].isoformat() if general_dates else None
        self.newest_published_at = general_dates[-1].isoformat() if general_dates else None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("failed_details")
        data["reached_since"] = self.reached_since
        return data


@dataclass(frozen=True)
class DetailRetryResult:
    attempted_urls: list[str]
    recovered: list[dict]
    still_failed: list[dict]


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
        post.content = "**[첨부파일 공지]**\n\n" + "\n".join(f"- {label}" for label in labels)


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
        labels = _asset_labels(inline_images)
        lines = [f"**[이미지 본문]** 텍스트 본문 없음 (이미지 {len(inline_images)}개)"]
        if labels:
            lines.append("")
            lines.extend(f"- {label}" for label in labels)
        post.content = "\n".join(lines)
        return

    if inline_embeds:
        labels = _asset_labels(inline_embeds)
        lines = [f"**[동영상 본문]** 텍스트 본문 없음 (동영상 {len(inline_embeds)}개)"]
        if labels:
            lines.append("")
            lines.extend(f"- {label}" for label in labels)
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
    since: date | None = None,
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
        since=since,
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
    since: date | None = None,
    keep_empty_content: bool = False,
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
        body_html = parser.body_html(fetch_result.html)
        inline_assets = extract_inline_image_assets(body_html, detail_url)
        inline_embeds = extract_inline_embed_assets(body_html, detail_url)
        _fill_missing_content_from_body_assets(
            post,
            inline_images=inline_assets,
            inline_embeds=inline_embeds,
        )
        _fill_missing_content_from_attachments(post)
        missing_fields = _missing_required_fields(post)
        # 연구 수집은 제목만 있고 본문·이미지·첨부가 모두 없는 공지도 남긴다(사이트 원문이 빈 경우).
        content_empty = keep_empty_content and missing_fields == ["content"]
        if missing_fields and not content_empty:
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
            since=since,
        )
        if not decision.include_post:
            return None, decision.stop_crawling

        post_dict = post.to_dict()
        post_dict["board_key"] = board.get("key")
        if inline_assets:
            post_dict["content_assets"] = inline_assets
        if content_empty:
            post_dict["content"] = ""
            post_dict["content_empty"] = True
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
    since: date | None = None,
    keep_empty_content: bool = False,
) -> tuple[list[dict], list[dict], BoardCrawlReport]:
    parser = adapter.parser_factory(board)
    board_label = _board_label(board)

    failed_items: list[dict] = []
    posts: list[dict] = []
    known_posts = known_posts_by_url if known_posts_by_url is not None else {}
    seen_for_board: set[str] = set(known_urls)
    seen_page_signatures: set[tuple[str, ...]] = set()
    page_limit = _resolve_page_limit(board, max_pages=max_pages, adapter=adapter)
    report = BoardCrawlReport(
        board_key=str(board.get("key") or ""),
        list_url=adapter.build_list_page_url(board, 1),
    )

    page = 1
    while page_limit is None or page <= page_limit:
        page_url = adapter.build_list_page_url(board, page)
        report.stop_page = page

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
            report.stop_reason = STOP_ROBOTS_DISALLOWED
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
            report.stop_reason = STOP_REQUEST_FAILED
            break

        page_items = _normalize_page_items(parser.parse_post_items(html, page_url), page=page)
        if not page_items:
            logger.info("수집 종료 | 게시판=%s | 사유=목록 없음 | 페이지=%s", board_label, page)
            report.stop_reason = STOP_EMPTY_LIST
            break

        page_signature = tuple(str(item.get("url") or "") for item in page_items)
        if page_signature in seen_page_signatures:
            logger.info("수집 종료 | 게시판=%s | 사유=반복 목록 | 페이지=%s", board_label, page)
            report.stop_reason = STOP_REPEATED_LIST
            break
        seen_page_signatures.add(page_signature)
        report.pages_read += 1

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
                if _evaluate_known_item_policy(
                    board,
                    detail_item,
                    known_posts_by_url=known_posts,
                    since=since,
                ):
                    logger.info(
                        "수집 종료 | 게시판=%s | 사유=기존 %s | 페이지=%s | url=%s",
                        board_label,
                        recent_stop_reason(since),
                        page,
                        detail_url,
                    )
                    report.stop_reason = STOP_SINCE_REACHED
                    stop_board = True
                    break
                continue

            seen_for_board.add(detail_url)
            failed_before = len(failed_items)
            post, should_stop = _parse_detail_item(
                board,
                detail_item,
                adapter=adapter,
                parser=parser,
                known_urls=known_urls,
                known_posts_by_url=known_posts,
                failed_items=failed_items,
                since=since,
                keep_empty_content=keep_empty_content,
            )
            if len(failed_items) > failed_before:
                report.failed_details.append({**detail_item, "reason": failed_items[-1]["reason"]})
            if post:
                posts.append(post)
            if should_stop:
                logger.info(
                    "수집 종료 | 게시판=%s | 사유=%s | 페이지=%s | url=%s",
                    board_label,
                    recent_stop_reason(since),
                    page,
                    detail_url,
                )
                report.stop_reason = STOP_SINCE_REACHED
                stop_board = True
                break

        if stop_board or stop_after_page:
            if stop_after_page and not stop_board:
                logger.info(
                    "수집 종료 | 게시판=%s | 사유=신규 일반공지 없음 | 페이지=%s",
                    board_label,
                    page,
                )
                report.stop_reason = STOP_NO_NEW_ITEMS
            break

        page += 1

    report.update_from_posts(posts)
    report.failed_items = len(failed_items)
    return posts, failed_items, report


def retry_failed_details(
    board: dict[str, Any],
    report: BoardCrawlReport,
    *,
    adapter: BoardAdapter,
    known_urls: set[str],
    known_posts_by_url: dict[str, dict],
    since: date | None = None,
    keep_empty_content: bool = False,
) -> DetailRetryResult:
    """수집 중 실패한 상세 공지를 한 번 더 시도한다.

    robots 차단은 다시 시도해도 같으므로 건너뛴다. 기간 경계 판정은 첫 시도와 같게 적용해
    재시도로 기간 밖 공지가 들어오지 않게 한다.
    """
    parser = adapter.parser_factory(board)
    attempted_urls: list[str] = []
    recovered: list[dict] = []
    still_failed: list[dict] = []

    for failed in report.failed_details:
        if failed.get("reason") == "robots_disallowed":
            continue
        detail_item = {key: failed[key] for key in ("url", "page", "is_permanent_notice")}
        attempted_urls.append(str(detail_item["url"]))
        post, _should_stop = _parse_detail_item(
            board,
            detail_item,
            adapter=adapter,
            parser=parser,
            known_urls=known_urls,
            known_posts_by_url=known_posts_by_url,
            failed_items=still_failed,
            since=since,
            keep_empty_content=keep_empty_content,
        )
        if post:
            recovered.append(post)

    return DetailRetryResult(
        attempted_urls=attempted_urls,
        recovered=recovered,
        still_failed=still_failed,
    )
