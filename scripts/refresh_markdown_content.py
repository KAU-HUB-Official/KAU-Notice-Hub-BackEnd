"""기존 JSON 스냅샷의 모든 공지를 다시 fetch & parse 해서 content를 Markdown으로 갱신.

사용:
    cd BackEnd
    .venv/bin/python -m scripts.refresh_markdown_content \
        --input data/kau_official_posts.json \
        --output data/kau_official_posts.json
    # --output 생략 시 input을 덮어쓰며, atomic rename으로 안전 교체.
    # --limit N으로 처음 N건만 시범 실행 가능.

다음을 수행한다:
- 각 post의 source_type을 NOTICE_BOARDS의 board와 매칭
- 해당 board adapter의 fetch_detail + parser_factory + parse_post로 재파싱
- 성공 시 post['content']와 부수 메타 일부(crawled_at)만 갱신, 나머지는 보존
- 실패 시 기존 post 그대로 유지 (잃지 않음)
- 진행 상황을 stderr에 로깅
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.crawler.config import NOTICE_BOARDS
from app.crawler.services.board_crawler import BoardAdapter
from app.crawler.services.board_registry import build_board_adapters, build_clients

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("scripts.refresh_markdown")


@dataclass
class RefreshStats:
    total: int = 0
    succeeded: int = 0
    failed_fetch: int = 0
    failed_parse: int = 0
    skipped_no_board: int = 0


def _resolve_board(
    post: dict[str, Any],
    board_index: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """post의 source_type을 board와 매칭. 병합된 공지로 list/tuple이면 순회한다."""
    raw = post.get("source_type")
    candidates: list[str]
    if isinstance(raw, (list, tuple)):
        candidates = [str(item) for item in raw if isinstance(item, str)]
    elif isinstance(raw, str):
        candidates = [raw]
    else:
        candidates = []

    for st in candidates:
        if st in board_index:
            return board_index[st]
    return None


def _build_board_index() -> dict[str, dict[str, Any]]:
    """source_type → board 메타 한 개로 인덱싱.

    같은 source_type을 공유하는 board가 여러 개인 경우(예: KAU 공식 7개 게시판)
    첫 번째 board를 representative로 사용한다. fetch_detail은 detail_url만
    있으면 동작하므로 어떤 board여도 무방하다.
    """
    index: dict[str, dict[str, Any]] = {}
    for board in NOTICE_BOARDS:
        st = board.get("source_type")
        if not st or st in index:
            continue
        index[st] = board
    return index


def _refresh_post(
    post: dict[str, Any],
    *,
    board: dict[str, Any],
    adapter: BoardAdapter,
    stats: RefreshStats,
) -> bool:
    detail_url = str(post.get("original_url") or "").strip()
    if not detail_url:
        stats.failed_fetch += 1
        return False

    try:
        fetch_result = adapter.fetch_detail(board, detail_url)
    except Exception:
        logger.exception("fetch_detail 예외 | url=%s", detail_url)
        stats.failed_fetch += 1
        return False

    html = fetch_result.html
    if not html:
        logger.warning(
            "fetch 실패 | url=%s | reason=%s",
            detail_url,
            fetch_result.failure_reason,
        )
        stats.failed_fetch += 1
        return False

    parser = adapter.parser_factory(board)
    try:
        new_post = parser.parse_post(html, detail_url)
    except Exception:
        logger.exception("parse 실패 | url=%s", detail_url)
        stats.failed_parse += 1
        return False

    new_content = (new_post.content or "").strip()
    if not new_content:
        logger.warning("새 content 비어 있음 | url=%s | 기존 유지", detail_url)
        stats.failed_parse += 1
        return False

    post["content"] = new_content
    post["crawled_at"] = datetime.now(timezone.utc).isoformat()
    stats.succeeded += 1
    return True


def refresh_snapshot(
    *,
    input_path: Path,
    output_path: Path,
    limit: int | None = None,
    sleep_seconds: float = 0.0,
) -> RefreshStats:
    posts = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(posts, list):
        raise SystemExit("입력 파일은 list여야 합니다.")

    board_index = _build_board_index()
    clients = build_clients()
    adapters = build_board_adapters(clients)
    stats = RefreshStats(total=len(posts))

    try:
        targets = posts if limit is None else posts[:limit]
        for index, post in enumerate(targets, start=1):
            board = _resolve_board(post, board_index)
            if not board:
                logger.warning(
                    "스킵 | source_type 매칭 board 없음 | url=%s | source_type=%s",
                    post.get("original_url"),
                    post.get("source_type"),
                )
                stats.skipped_no_board += 1
                continue

            adapter = adapters.get(board["board_type"])
            if adapter is None:
                stats.skipped_no_board += 1
                continue

            _refresh_post(post, board=board, adapter=adapter, stats=stats)

            if index % 50 == 0 or index == len(targets):
                logger.info(
                    "진행 | %d/%d | 성공=%d 실패fetch=%d 실패parse=%d 스킵=%d",
                    index,
                    len(targets),
                    stats.succeeded,
                    stats.failed_fetch,
                    stats.failed_parse,
                    stats.skipped_no_board,
                )

            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
    finally:
        clients.close()

    # atomic write: tmp → rename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(posts, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp_path, output_path)
    logger.info("저장 완료 | %s", output_path)

    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="기존 공지 JSON content를 Markdown으로 재파싱")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/kau_official_posts.json"),
        help="입력 JSON 경로",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="출력 JSON 경로. 미지정 시 입력 파일을 덮어씀",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="처음 N건만 처리 (시범 실행용)",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="요청 사이 sleep(초). KAU 서버 부담 줄이고 싶으면 0.2 등 지정",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = args.output or args.input
    stats = refresh_snapshot(
        input_path=args.input,
        output_path=output_path,
        limit=args.limit,
        sleep_seconds=args.sleep,
    )
    logger.info(
        "완료 | 전체=%d 성공=%d 실패fetch=%d 실패parse=%d 스킵=%d",
        stats.total,
        stats.succeeded,
        stats.failed_fetch,
        stats.failed_parse,
        stats.skipped_no_board,
    )


if __name__ == "__main__":
    main()
