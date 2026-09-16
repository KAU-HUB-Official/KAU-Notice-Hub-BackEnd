"""연구 원본에서 college 게시판 공지의 상세만 다시 받아 새 원본을 만든다.

college 상세 API는 이전·다음 글 본문도 함께 주는데, 크롤러가 응답 전체에서 본문 이미지를 뽑아 다른 글의
이미지가 공지에 붙었다(2026-09-15 확인). 크롤러를 고친 뒤 목록은 그대로 두고 상세만 같은 코드 경로로 다시
파싱한다. 원본은 덮어쓰지 않는다. 다른 게시판 공지는 그대로 옮긴다.

실행 (BackEnd 루트):
    CRAWLER_REQUEST_DELAY_SECONDS=0.1,0.3 .venv/bin/python -m scripts.research.refetch_college_details \\
        --input data/research/kau_notices_raw_2026-09-15.json \\
        --output data/research/kau_notices_raw_2026-09-15_college_refetch.json \\
        --report data/research/college_refetch_report_2026-09-15.json --since 2023-01-01
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.crawler.config import NOTICE_BOARDS
from app.crawler.services.board_crawler import _parse_detail_item
from app.crawler.services.board_registry import build_board_adapters, build_clients

COMPARED_FIELDS = ("title", "content", "content_assets", "attachments", "published_at")


def _image_urls(post: dict[str, Any]) -> list[str]:
    return [str(a.get("url")) for a in post.get("content_assets") or [] if isinstance(a, dict)]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, required=True, help="연구 수집 원본 JSON")
    parser.add_argument("--output", type=Path, required=True, help="college 상세를 다시 받은 새 원본 JSON")
    parser.add_argument("--report", type=Path, required=True, help="바뀐 공지 기록 JSON")
    parser.add_argument("--since", type=date.fromisoformat, required=True, help="원본 수집의 --since")
    args = parser.parse_args(argv)
    if args.output.resolve() == args.input.resolve() or args.output.exists():
        parser.error("원본을 덮어쓰거나 이미 있는 파일에 쓰지 않습니다.")

    posts = json.loads(args.input.read_text(encoding="utf-8"))
    boards = {board["key"]: board for board in NOTICE_BOARDS}
    targets = [i for i, p in enumerate(posts) if boards.get(p.get("board_key"), {}).get("board_type") == "kau_college"]
    print(f"college 공지 {len(targets)}건 / 전체 {len(posts)}건")

    clients = build_clients()
    adapter = build_board_adapters(clients)["kau_college"]
    parsers: dict[str, Any] = {}
    stats: Counter[str] = Counter()
    changes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        for n, index in enumerate(targets, 1):
            old = posts[index]
            board = boards[old["board_key"]]
            item = {"url": old["original_url"], "page": 1, "is_permanent_notice": bool(old.get("is_permanent_notice"))}
            new = None
            failed: list[dict] = []
            for attempt in range(2):
                failed = []
                new, _stop = _parse_detail_item(
                    board,
                    item,
                    adapter=adapter,
                    parser=parsers.setdefault(board["key"], adapter.parser_factory(board)),
                    known_urls=set(),
                    known_posts_by_url={},
                    failed_items=failed,
                    since=args.since,
                )
                if new is not None or attempt:
                    break
                time.sleep(2)
            if new is None or new["original_url"] != old["original_url"]:
                stats["failed"] += 1
                failures.append({"url": old["original_url"], "failed_items": failed, "got_url": new and new["original_url"]})
                continue

            changed = [f for f in COMPARED_FIELDS if (old.get(f) or None) != (new.get(f) or None)]
            stats["refetched"] += 1
            for field in changed:
                stats[f"changed:{field}"] += 1
            if changed:
                old_images, new_images = _image_urls(old), _image_urls(new)
                changes.append(
                    {
                        "url": old["original_url"],
                        "board_key": old["board_key"],
                        "title": new["title"],
                        "changed": changed,
                        "images_removed": [u for u in old_images if u not in new_images],
                        "images_added": [u for u in new_images if u not in old_images],
                        "content_before": (old.get("content") or "")[:200],
                        "content_after": (new.get("content") or "")[:200],
                    }
                )
            posts[index] = new
            if n % 200 == 0:
                print(f"  {n}/{len(targets)} {dict(stats)}")
    finally:
        clients.close()

    args.output.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {"targets": len(targets), **dict(sorted(stats.items()))}
    args.report.write_text(
        json.dumps(
            {
                "started_at": started_at,
                "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "input": str(args.input),
                "output": str(args.output),
                "summary": summary,
                "failures": failures,
                "changes": changes,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print("saved", args.output, args.report)


if __name__ == "__main__":
    main()
