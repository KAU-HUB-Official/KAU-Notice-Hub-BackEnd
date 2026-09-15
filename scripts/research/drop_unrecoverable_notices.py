"""본문을 되살릴 수 없는 공지를 연구 데이터에서 뺀다. 입력 파일은 덮어쓰지 않고 걸러낸 사본을 쓴다.

제외 대상: 보강 캐시를 적용한 뒤에도 여전히 보강 대상인 공지. 본문에 텍스트가 없이 이미지뿐인데
그 이미지에서 텍스트를 뽑지 못한 공지(이미지 주소가 사라졌거나 파일을 받을 수 없음)라서 내용을 알 수 없다.
남기는 공지: 이미지 일부가 깨졌어도 본문 텍스트가 있거나 보강에 성공한 공지, 사이트 원문 자체가 제목만 있는
공지(content_empty, 보강 대상 아님).
제외 뒤 구성원이 1건만 남은 교차 게시 그룹은 crosspost_group_id를 비운다.

예 (네트워크·OpenAI 호출 없음):
    .venv/bin/python -m scripts.research.drop_unrecoverable_notices \\
        --input data/research/kau_notices_enriched_2026-09-15.json \\
        --cache data/research/enrichment_cache.json \\
        --output data/research/kau_notices_clean_2026-09-15.json \\
        --removed data/research/removed_unrecoverable_2026-09-15.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.crawler.services.content_enrichment_service import ContentEnrichmentService
from scripts.research.enrich_cache import EnrichmentCache, build_service

GROUP_FIELD = "crosspost_group_id"


def split_unrecoverable(
    posts: list[dict[str, Any]],
    service: ContentEnrichmentService,
    cache: EnrichmentCache,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """(남길 공지 사본, 제외 기록, 비운 교차 게시 그룹 수)를 돌려준다."""
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for post in posts:
        if not service.should_enrich(post):
            kept.append(dict(post))
            continue
        assets = []
        for asset in service.find_supported_assets(post):
            entry = cache.assets.get(asset.url)
            assets.append(
                {
                    "type": asset.type,
                    "url": asset.url if not asset.url.startswith("data:") else "data:(생략)",
                    "extracted": bool(entry and not entry.get("error")),
                    "cached_error": entry.get("error") if entry else None,
                }
            )
        removed.append(
            {
                "original_url": post.get("original_url"),
                "title": post.get("title"),
                "published_at": post.get("published_at"),
                "board_key": post.get("board_key"),
                GROUP_FIELD: post.get(GROUP_FIELD),
                "assets": assets,
            }
        )

    sizes = Counter(p.get(GROUP_FIELD) for p in kept if p.get(GROUP_FIELD))
    cleared = {group for group, size in sizes.items() if size < 2}
    for post in kept:
        if post.get(GROUP_FIELD) in cleared:
            post[GROUP_FIELD] = None
    return kept, removed, len(cleared)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="본문을 되살릴 수 없는 공지를 뺀다.")
    parser.add_argument("--input", type=Path, required=True, help="보강을 적용한 공지 JSON")
    parser.add_argument("--cache", type=Path, required=True, help="보강 캐시 JSON")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--removed", type=Path, required=True, help="제외 기록 JSON")
    args = parser.parse_args(argv)
    if args.output.resolve() == args.input.resolve():
        parser.error("입력 파일을 덮어쓰지 않습니다.")

    posts = json.loads(args.input.read_text(encoding="utf-8"))
    cache = EnrichmentCache(args.cache)
    service = build_service(get_settings(), cache)  # 캐시만 보는 서비스. 판정에 네트워크를 쓰지 않는다.
    kept, removed, cleared = split_unrecoverable(posts, service, cache)

    summary = {
        "input": str(args.input),
        "posts": len(posts),
        "removed": len(removed),
        "kept": len(kept),
        "cleared_crosspost_groups": cleared,
        "removed_by_year": dict(sorted(Counter(str(r["published_at"])[:4] for r in removed).items())),
        "removed_by_board": dict(Counter(r["board_key"] for r in removed).most_common()),
        "removed_asset_hosts": dict(
            Counter(
                a["url"].split("/")[2] if "://" in a["url"] else a["url"] for r in removed for a in r["assets"]
            ).most_common()
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    args.removed.write_text(
        json.dumps(
            {
                "rule": "보강 캐시를 적용한 뒤에도 본문 텍스트가 없고 이미지에서 텍스트를 뽑지 못한 공지를 제외",
                "summary": summary,
                "removed": removed,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
