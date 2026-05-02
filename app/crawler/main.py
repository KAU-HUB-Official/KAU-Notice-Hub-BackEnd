from __future__ import annotations

import argparse
from pathlib import Path

from app.config import get_settings

from .config import DEFAULT_MAX_PAGES, FAILED_OUTPUT_FILE, NOTICE_BOARDS, OUTPUT_FILE
from .services.board_crawler import crawl_board
from .services.board_registry import build_board_adapters, build_clients
from .services.content_enrichment_service import ContentEnrichmentService
from .services.dedup_service import merge_posts_with_dedup, prune_stale_posts
from .services.post_store import load_existing_posts
from .services.url_normalizer import canonicalize_original_url
from .utils.logger import get_logger
from .utils.save_json import save_json

logger = get_logger("crawler.main")


def crawl_all_notices(max_pages: int, output_path: Path) -> tuple[list[dict], list[dict]]:
    clients = build_clients()
    adapters = build_board_adapters(clients)

    try:
        existing_posts = load_existing_posts(output_path)
        known_posts_by_url: dict[str, dict] = {}
        for post in existing_posts:
            original_url = canonicalize_original_url(str(post.get("original_url") or ""))
            if original_url:
                known_posts_by_url[original_url] = post

            for meta in post.get("source_meta") or []:
                if not isinstance(meta, dict):
                    continue
                meta_url = canonicalize_original_url(str(meta.get("original_url") or ""))
                if meta_url:
                    known_posts_by_url[meta_url] = meta

        known_urls = set(known_posts_by_url)

        all_new_posts: list[dict] = []
        all_failed_items: list[dict] = []

        logger.info(
            "공지 게시판 수집 시작: 게시판=%s, 페이지상한=%s, 기존보유URL=%s",
            len(NOTICE_BOARDS),
            "자동" if max_pages <= 0 else max_pages,
            len(known_urls),
        )

        for board in NOTICE_BOARDS:
            logger.info("게시판 수집 시작: %s", board["name"])

            adapter = adapters.get(board["board_type"])
            if adapter is None:
                logger.warning("지원하지 않는 board_type: %s", board["board_type"])
                continue

            posts, failed_items = crawl_board(
                board,
                max_pages=max_pages,
                adapter=adapter,
                known_urls=known_urls,
                known_posts_by_url=known_posts_by_url,
            )
            all_new_posts.extend(posts)
            all_failed_items.extend(failed_items)

        merge_result = merge_posts_with_dedup(existing_posts, all_new_posts)
        prune_result = prune_stale_posts(merge_result.posts)
        settings = get_settings()
        if settings.content_enrichment_enabled:
            enrichment_result = ContentEnrichmentService.from_settings(settings).enrich_posts(
                prune_result.posts
            )
            logger.info(
                (
                    "content enrichment 완료: attempted=%s, succeeded=%s, failed=%s, "
                    "skipped=%s, calls_used=%s"
                ),
                enrichment_result.attempted,
                enrichment_result.succeeded,
                enrichment_result.failed,
                enrichment_result.skipped,
                enrichment_result.calls_used,
            )

        save_json(prune_result.posts, output_path)
        logger.info(
            (
                "결과 저장 완료: %s "
                "(total=%s, newly_added=%s, url_dedup_removed=%s, "
                "title_dedup_removed=%s, stale_pruned=%s)"
            ),
            output_path,
            len(prune_result.posts),
            len(all_new_posts),
            merge_result.url_dedup_removed,
            merge_result.title_dedup_removed,
            prune_result.stale_pruned,
        )

        if all_failed_items:
            save_json(all_failed_items, FAILED_OUTPUT_FILE)
            logger.warning(
                "실패 로그 저장 완료: %s (count=%s)",
                FAILED_OUTPUT_FILE,
                len(all_failed_items),
            )
        elif FAILED_OUTPUT_FILE.exists():
            FAILED_OUTPUT_FILE.unlink()
            logger.info("실패 항목이 없어 기존 실패 로그 파일 삭제: %s", FAILED_OUTPUT_FILE)

        return prune_result.posts, all_failed_items
    finally:
        clients.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="한국항공대학교 통합 공지 크롤러",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help=(
            "게시판별 목록 페이지 상한. 0이면 페이지 상한 없이 최근성 정책으로 자동 중단 "
            f"(기본값: {DEFAULT_MAX_PAGES})"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_FILE,
        help=f"결과 JSON 저장 경로 (기본값: {OUTPUT_FILE})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    crawl_all_notices(max_pages=args.max_pages, output_path=args.output)


if __name__ == "__main__":
    main()
