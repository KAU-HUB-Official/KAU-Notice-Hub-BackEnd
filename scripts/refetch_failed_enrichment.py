"""본문 보강에 실패한 공지를 지금 크롤러로 다시 읽어, 원문이 달라졌으면 스냅샷에 반영한다.

2026-05~06에 예전 크롤러가 모은 공지 일부는 본문 이미지가 깨진 채 남아 있다(2026-11-08 확인).
data URL 이미지 base64 안의 `//`가 `/`로 줄었거나, 이미지 주소가 `/web/pages/\\"https:/...`처럼 망가졌다.
지금 크롤러는 같은 원문을 바르게 읽지만, 수정 확인(notice_update)은 최근·상시 공지만 다시 읽고
제목·본문·첨부 해시가 같으면 이미지를 바꾸지 않아 이런 공지가 고쳐지지 않고 보강만 매번 실패했다.

- 대상: content_enrichment.status 가 failed 인 공지 (--url 로 직접 고를 수도 있다)
- 상세를 크롤러와 같은 경로(_parse_detail_item)로 다시 읽고, 해시나 본문 이미지가 다르면
  apply_notice_update 로 바꾼다. 옛 보강 기록이 지워져 다음 정기 수집이 새 원문으로 다시 보강한다.
- 기본은 미리보기다(학교 사이트만 읽고 파일은 그대로). --apply 를 주면 크롤러 게시 잠금을 잡은 채
  원본을 <파일>.bak-<시각> 으로 복사하고 atomic 하게 바꾼다. OpenAI 는 부르지 않는다.

실행 (운영 서버, api 컨테이너 안에서):
    docker compose exec api python -m scripts.refetch_failed_enrichment            # 미리보기
    docker compose exec api python -m scripts.refetch_failed_enrichment --apply    # 반영
DB 는 다음 정기 수집이 보강 뒤 다시 적재한다.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.config import get_settings
from app.crawler.config import NOTICE_BOARDS
from app.crawler.services.board_crawler import _parse_detail_item
from app.crawler.services.board_registry import build_board_adapters, build_clients
from app.crawler.services.notice_update import apply_notice_update
from app.crawler_scheduler import FileLock

FreshFetcher = Callable[[dict[str, Any]], dict[str, Any] | None]


def select_targets(posts: list[dict[str, Any]], urls: list[str]) -> list[dict[str, Any]]:
    if urls:
        wanted = set(urls)
        return [post for post in posts if post.get("original_url") in wanted]
    return [
        post
        for post in posts
        if isinstance(post.get("content_enrichment"), dict) and post["content_enrichment"].get("status") == "failed"
    ]


def refetch_posts(targets: list[dict[str, Any]], fetch: FreshFetcher) -> list[dict[str, Any]]:
    """targets 를 제자리에서 고치고, 공지별 결과(status)를 돌려준다."""
    results = []
    for post in targets:
        label = {"url": str(post.get("original_url") or ""), "title": str(post.get("title") or "")}
        fresh = fetch(post)
        if fresh is None:
            results.append({**label, "status": "읽기 실패"})
            continue
        # 새 원문에 본문 이미지가 없으면 옛 이미지 목록도 지운다(apply_notice_update 는 없는 키를 건너뛴다).
        fresh.setdefault("content_assets", [])
        if fresh.get("content_hash") == post.get("content_hash") and fresh["content_assets"] == (post.get("content_assets") or []):
            results.append({**label, "status": "같음"})
            continue
        results.append(
            {
                **label,
                "status": "바꿈",
                "assets_before": len(post.get("content_assets") or []),
                "assets_after": len(fresh["content_assets"]),
            }
        )
        apply_notice_update(post, fresh)
    return results


def _board_for(post: dict[str, Any]) -> dict[str, Any] | None:
    """게시판 설정을 찾는다. college 게시판은 상세 API에 게시판별 mnuId 를 보내므로 주소 경로로 맞춘다."""
    by_key = {board.get("key"): board for board in NOTICE_BOARDS}
    if post.get("board_key") in by_key:
        return by_key[post["board_key"]]
    path = urlparse(str(post.get("original_url") or "")).path
    for board in NOTICE_BOARDS:
        if urlparse(str(board.get("list_url") or "")).path == path:
            return board
    source_types = post.get("source_type")
    candidates = source_types if isinstance(source_types, list) else [source_types]
    for board in NOTICE_BOARDS:
        if board.get("source_type") in candidates:
            return board
    return None


def build_crawler_fetcher() -> FreshFetcher:
    adapters = build_board_adapters(build_clients())

    def fetch(post: dict[str, Any]) -> dict[str, Any] | None:
        board = _board_for(post)
        adapter = adapters.get(board["board_type"]) if board else None
        if board is None or adapter is None:
            return None
        fresh, _ = _parse_detail_item(
            board,
            {"url": post["original_url"], "page": 1, "is_permanent_notice": bool(post.get("is_permanent_notice"))},
            adapter=adapter,
            parser=adapter.parser_factory(board),
            known_urls=set(),
            known_posts_by_url={},
            failed_items=[],
            # 오래된 공지도 읽도록 게시일 기준을 끈다.
            since=date.min,
        )
        return fresh

    return fetch


def _write_atomic(path: Path, posts: list[dict[str, Any]]) -> Path:
    backup = path.with_name(f"{path.name}.bak-{datetime.now().strftime('%Y%m%d%H%M%S')}")
    backup.write_bytes(path.read_bytes())
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False, encoding="utf-8"
    ) as tmp:
        json.dump(posts, tmp, ensure_ascii=False, indent=2)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)
    return backup


def run(notices: Path, urls: list[str], apply: bool, fetch: FreshFetcher) -> list[dict[str, Any]]:
    posts = json.loads(notices.read_text(encoding="utf-8"))
    results = refetch_posts(select_targets(posts, urls), fetch)
    for r in results:
        head = f"  {r['status']:<6} | {r['title'][:40]}"
        print(head + (f" | 본문 이미지 {r['assets_before']}개 → {r['assets_after']}개" if r["status"] == "바꿈" else ""))
    changed = sum(1 for r in results if r["status"] == "바꿈")
    print(json.dumps({"대상": len(results), "바꿈": changed, "같음": sum(1 for r in results if r["status"] == "같음"),
                      "읽기 실패": sum(1 for r in results if r["status"] == "읽기 실패")}, ensure_ascii=False))
    if not apply:
        print("미리보기입니다. 반영하려면 --apply 를 주세요.")
    elif not changed:
        print("바꿀 공지가 없어 파일을 건드리지 않았습니다.")
    else:
        print(f"반영했습니다. 원본 복사본: {_write_atomic(notices, posts)}")
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--notices", type=Path, default=None, help="공지 스냅샷 JSON (기본 NOTICE_JSON_PATH)")
    parser.add_argument("--url", action="append", default=[], help="이 공지만 다시 읽는다 (여러 번 줄 수 있다)")
    parser.add_argument("--apply", action="store_true", help="실제로 파일을 바꾼다. 없으면 미리보기만 한다")
    args = parser.parse_args(argv)

    settings = get_settings()
    notices = (args.notices or settings.notice_json_path).expanduser().resolve()
    if not args.apply:
        run(notices, args.url, False, build_crawler_fetcher())
        return
    # 정기 수집이 같은 파일을 다시 쓰지 않도록 크롤러 게시 잠금을 잡은 채 읽고 쓴다.
    lock_path = (settings.crawler_lock_path or notices.parent / ".crawler.lock").expanduser().resolve()
    with FileLock(lock_path) as acquired:
        if not acquired:
            raise SystemExit("크롤러가 수집 중입니다. 끝난 뒤 다시 실행하세요.")
        run(notices, args.url, True, build_crawler_fetcher())


if __name__ == "__main__":
    main()
