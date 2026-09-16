from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from app.config import get_settings

from .config import (
    DEFAULT_MAX_PAGES,
    FAILED_OUTPUT_FILE,
    NOTICE_BOARDS,
    OUTPUT_FILE,
    PROJECT_ROOT,
    RECENT_NOTICE_DAYS,
    REQUEST_DELAY_SECONDS,
)
from .services.board_crawler import (
    BoardAdapter,
    BoardCrawlReport,
    crawl_board,
    retry_failed_details,
)
from .services.board_registry import build_board_adapters, build_clients
from .services.content_enrichment_service import ContentEnrichmentService
from .services.dedup_service import (
    RetentionPruneResult,
    merge_posts_with_dedup,
    prune_stale_posts,
)
from .services.post_store import load_existing_posts
from .services.url_normalizer import canonicalize_original_url
from .utils.logger import get_logger
from .utils.save_json import save_json

logger = get_logger("crawler.main")

# 기간 경계에 닿지 못하고 멈췄는데 가장 오래된 일반공지가 since보다 이만큼 넘게 늦은 게시판은,
# 게시판이 늦게 생긴 것인지 페이지 넘김이 실패한 것인지 사람이 확인하도록 따로 모은다.
REVIEW_GRACE_DAYS = 90


def _board_label(board: dict) -> str:
    name = str(board.get("name") or board.get("key") or "").strip()
    return name.removesuffix("공지사항").strip() or name


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _git_state() -> dict | None:
    """수집 기록에 남길 코드 커밋과 미커밋 파일 수. git을 쓸 수 없으면 None."""
    try:
        commit = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return {
        "commit": commit,
        "uncommitted_files": sum(1 for line in status.splitlines() if line.strip()),
    }


def boards_to_review(reports: list[BoardCrawlReport], since: date) -> list[dict]:
    limit = since + timedelta(days=REVIEW_GRACE_DAYS)
    review: list[dict] = []
    for report in reports:
        if report.reached_since:
            continue
        oldest = report.oldest_published_at
        if oldest is not None and date.fromisoformat(oldest) <= limit:
            continue
        review.append(
            {
                "board_key": report.board_key,
                "stop_reason": report.stop_reason,
                "stop_page": report.stop_page,
                "pages_read": report.pages_read,
                "posts": report.posts,
                "oldest_published_at": oldest,
            }
        )
    return review


def crawl_all_notices(
    max_pages: int,
    output_path: Path,
    *,
    since: date | None = None,
    research: bool = False,
    manifest_path: Path | None = None,
    failed_output_path: Path | None = None,
    command: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """공지를 수집해 output_path에 저장한다.

    research=True는 연구용 원본 수집이다. 운영 기본 동작과 달리
    - 제목이 같아도 합치지 않고 URL 기준 중복 제거만 한다(해마다 같은 제목으로 올라오는 회차 보존).
    - 오래된 공지 삭제와 본문 보강을 하지 않는다.
    - 실패한 상세 공지를 수집 끝에 한 번 더 시도하고, 게시판별 수집 기록(manifest)을 남긴다.
    원본을 덮어쓰지 않도록 output_path가 이미 있거나, 수집 조건을 커밋 하나로 남길 수 없도록
    미커밋 파일이 있으면 시작하지 않는다.
    """
    git_state: dict | None = None
    if research:
        if since is None:
            raise ValueError("연구 수집은 since 날짜가 필요합니다.")
        if output_path.exists():
            raise FileExistsError(f"연구 수집 원본은 덮어쓰지 않습니다: {output_path}")
        git_state = _git_state()
        if git_state is None or git_state["uncommitted_files"]:
            raise RuntimeError(
                f"연구 수집은 미커밋 파일이 없는 커밋에서만 실행합니다: git={git_state}"
            )
        manifest_path = manifest_path or output_path.with_name(f"{output_path.stem}.manifest.json")
        failed_output_path = failed_output_path or output_path.with_name(
            f"{output_path.stem}.failed.json"
        )

    started_at = _now()
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
        board_runs: list[tuple[dict, BoardAdapter, list[dict], BoardCrawlReport]] = []
        unsupported_boards: list[str] = []

        logger.info(
            "수집 시작 | 게시판수=%s | 페이지상한=%s | 기존URL=%s",
            len(NOTICE_BOARDS),
            "자동" if max_pages <= 0 else max_pages,
            len(known_urls),
        )
        if research or since is not None:
            logger.info("수집 조건 | 연구모드=%s | since=%s", research, since)

        for board in NOTICE_BOARDS:
            adapter = adapters.get(board["board_type"])
            if adapter is None:
                logger.warning(
                    "지원 제외 | 게시판=%s | board_type=%s",
                    _board_label(board),
                    board["board_type"],
                )
                unsupported_boards.append(str(board.get("key")))
                continue

            posts, failed_items, report = crawl_board(
                board,
                max_pages=max_pages,
                adapter=adapter,
                known_urls=known_urls,
                known_posts_by_url=known_posts_by_url,
                since=since,
            )
            all_new_posts.extend(posts)
            all_failed_items.extend(failed_items)
            board_runs.append((board, adapter, posts, report))

        retry_record: dict | None = None
        if research:
            attempted: list[str] = []
            recovered_urls: list[str] = []
            still_failed: list[dict] = []
            for board, adapter, posts, report in board_runs:
                if not report.failed_details:
                    continue
                result = retry_failed_details(
                    board,
                    report,
                    adapter=adapter,
                    known_urls=known_urls,
                    known_posts_by_url=known_posts_by_url,
                    since=since,
                )
                posts.extend(result.recovered)
                all_new_posts.extend(result.recovered)
                report.update_from_posts(posts)
                report.failed_items += len(result.still_failed) - len(result.attempted_urls)
                attempted.extend(result.attempted_urls)
                recovered_urls.extend(post["original_url"] for post in result.recovered)
                still_failed.extend(result.still_failed)

            retried = set(attempted)
            all_failed_items = [
                item for item in all_failed_items if item.get("url") not in retried
            ] + still_failed
            retry_record = {
                "attempted": len(attempted),
                "recovered": recovered_urls,
                "still_failed": still_failed,
            }
            logger.info(
                "실패 재시도 | 시도=%s | 복구=%s | 남은실패=%s",
                len(attempted),
                len(recovered_urls),
                len(still_failed),
            )

        merge_result = merge_posts_with_dedup(
            existing_posts,
            all_new_posts,
            merge_title_duplicates=not research,
        )
        content_enrichment_enabled = False
        if research:
            prune_result = RetentionPruneResult(posts=merge_result.posts, stale_pruned=0)
        else:
            prune_result = prune_stale_posts(merge_result.posts)
            settings = get_settings()
            content_enrichment_enabled = settings.content_enrichment_enabled
            if settings.content_enrichment_enabled:
                enrichment_result = ContentEnrichmentService.from_settings(settings).enrich_posts(
                    prune_result.posts
                )
                logger.info(
                    (
                        "본문 보강 | 보강대상=%s | 시도=%s "
                        "| 성공=%s | 실패=%s | 호출=%s"
                    ),
                    enrichment_result.target_count,
                    enrichment_result.attempted,
                    enrichment_result.succeeded,
                    enrichment_result.failed,
                    enrichment_result.calls_used,
                )

        save_json(prune_result.posts, output_path)
        logger.info(
            (
                "저장 완료 | 전체=%s | 신규=%s | URL중복=%s "
                "| 제목중복=%s | 오래된공지삭제=%s | 경로=%s"
            ),
            len(prune_result.posts),
            len(all_new_posts),
            merge_result.url_dedup_removed,
            merge_result.title_dedup_removed,
            prune_result.stale_pruned,
            output_path,
        )

        if research:
            save_json(all_failed_items, failed_output_path)
            logger.info("실패 저장 | 건수=%s | 경로=%s", len(all_failed_items), failed_output_path)
        elif all_failed_items:
            save_json(all_failed_items, FAILED_OUTPUT_FILE)
            logger.warning(
                "실패 저장 | 건수=%s | 경로=%s",
                len(all_failed_items),
                FAILED_OUTPUT_FILE,
            )
        elif FAILED_OUTPUT_FILE.exists():
            FAILED_OUTPUT_FILE.unlink()
            logger.info("실패 없음 | 기존 실패 파일 삭제 | 경로=%s", FAILED_OUTPUT_FILE)

        if manifest_path is not None:
            reports = [report for _, _, _, report in board_runs]
            review = boards_to_review(reports, since) if since is not None else []
            save_json(
                {
                    "started_at": started_at,
                    "finished_at": _now(),
                    "command": command,
                    "git": git_state if research else _git_state(),
                    "options": {
                        "research": research,
                        "since": since.isoformat() if since else None,
                        "max_pages": max_pages,
                        "output": str(output_path),
                        "failed_output": str(failed_output_path or FAILED_OUTPUT_FILE),
                    },
                    "request_delay_seconds": list(REQUEST_DELAY_SECONDS),
                    "recent_notice_days": None if research else RECENT_NOTICE_DAYS,
                    "content_enrichment": content_enrichment_enabled,
                    "totals": {
                        "new_posts": len(all_new_posts),
                        "saved_posts": len(prune_result.posts),
                        "url_dedup_removed": merge_result.url_dedup_removed,
                        "title_dedup_removed": merge_result.title_dedup_removed,
                        "stale_pruned": prune_result.stale_pruned,
                        "failed_items": len(all_failed_items),
                    },
                    "retry": retry_record,
                    "boards": [report.to_dict() for report in reports],
                    "unsupported_boards": unsupported_boards,
                    "review_rule": (
                        "stop_reason이 since_reached가 아니고, 가장 오래된 일반공지가 없거나 "
                        f"since + {REVIEW_GRACE_DAYS}일보다 늦음"
                    ),
                    "review_boards": review,
                },
                manifest_path,
            )
            for item in review:
                logger.warning(
                    "확인 필요 | 게시판=%s | 중단사유=%s | 페이지=%s | 가장오래된일반공지=%s",
                    item["board_key"],
                    item["stop_reason"],
                    item["stop_page"],
                    item["oldest_published_at"],
                )
            logger.info("수집 기록 저장 | 확인필요게시판=%s | 경로=%s", len(review), manifest_path)

        return prune_result.posts, all_failed_items
    finally:
        clients.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
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
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        default=None,
        help=(
            "이 날짜(YYYY-MM-DD)보다 먼저 게시된 일반공지를 만나면 게시판 수집을 멈춘다. "
            "상시공지는 날짜와 무관하게 수집한다. 없으면 CRAWLER_RECENT_NOTICE_DAYS 기준"
        ),
    )
    parser.add_argument(
        "--research",
        action="store_true",
        help=(
            "연구용 원본 수집. URL 기준 중복 제거만 하고 오래된 공지 삭제·본문 보강을 하지 않으며, "
            "본문 빈 공지를 남기고 실패 공지를 한 번 더 시도한 뒤 수집 기록을 저장한다. "
            "--since 필요. 출력 파일이 이미 있거나 미커밋 파일이 있으면 시작하지 않는다"
        ),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="게시판별 수집 기록 JSON 경로 (연구 모드 기본값: <output 이름>.manifest.json)",
    )
    parser.add_argument(
        "--failed-output",
        type=Path,
        default=None,
        help="실패 항목 JSON 경로 (연구 모드 기본값: <output 이름>.failed.json)",
    )
    args = parser.parse_args(argv)
    if args.research and args.since is None:
        parser.error("--research 는 --since 와 함께 써야 합니다.")
    return args


def main() -> None:
    args = parse_args()
    crawl_all_notices(
        max_pages=args.max_pages,
        output_path=args.output,
        since=args.since,
        research=args.research,
        manifest_path=args.manifest,
        failed_output_path=args.failed_output,
        command=shlex.join(["python", "-m", "app.crawler.main", *sys.argv[1:]]),
    )


if __name__ == "__main__":
    main()
