"""3년치 공지에서 교차 게시 후보 쌍을 뽑아 규칙으로 정할 수 있는 쌍과 판정이 필요한 쌍으로 나눈다.

질문: 두 공지를 하나로 합쳐 본문 하나만 남겨도 읽는 사람에게 지장이 없는가.

순서 (규칙 정의는 crosspost_rules.py)
1. 후보: 게시판이 다르고 게시일 차이 7일 이내, 제목이 같거나 비슷함(2-gram 0.8 이상).
2. 첨부파일 규칙: 첨부파일 이름·개수가 전부 같으면 합침.
3. 본문 유사도 0.9 이상이면 합침. 한쪽 본문이 50자 미만이면 비교 불가로 다음 단계로 넘긴다.
4. 본문 이미지 규칙: 본문 이미지 파일(해시)·개수가 전부 같으면 합침.
   해시는 3단계까지 정하지 못한 쌍의 이미지만 구한다. 보강 캐시에 있으면 쓰고, 없으면 학교 서버에서 내려받는다.
5. 나머지는 판정 필요 (본문 유사도 구간별로 센다).

실행 (BackEnd 루트):
    .venv/bin/python -m scripts.research.classify_crosspost_pairs \\
        --posts data/research/kau_notices_clean_2026-09-15.json \\
        --enrichment-cache data/research/enrichment_cache.json \\
        --image-hash-cache data/research/image_hash_cache.json \\
        --output data/research/crosspost_pairs_2026-09-15.json
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.crawler.policies.notice_policy import parse_published_date
from app.crawler.services.content_asset_downloader import (
    ContentAsset,
    ContentAssetDownloader,
    ContentAssetDownloadError,
)
from scripts.research.crosspost_rules import (
    BODY_AUTO_MERGE,
    CANDIDATE_WINDOW_DAYS,
    body_for_similarity,
    body_image_urls,
    body_similarity,
    loose_title,
    same_attachment_set,
    same_body_image_set,
    similar_titles,
)

ATTACHMENT_RULE = "첨부파일 일치"
BODY_RULE = "본문 90% 이상"
IMAGE_RULE = "본문 이미지 일치"
NEEDS_JUDGMENT = "판정 필요"


def similarity_bin(sim: float | None) -> str:
    if sim is None:
        return "비교 불가(한쪽 본문 50자 미만)"
    return "<0.3" if sim < 0.3 else "0.3~0.6" if sim < 0.6 else "0.6~0.9"


def candidate_pairs(posts: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """게시일 순으로 정렬된 posts에서 후보 쌍 (i, j)."""
    dates = [parse_published_date(p["published_at"]) for p in posts]
    titles = [loose_title(p["title"]) for p in posts]
    pairs = []
    for i, a in enumerate(posts):
        for j in range(i + 1, len(posts)):
            if (dates[j] - dates[i]).days > CANDIDATE_WINDOW_DAYS:
                break
            if posts[j]["board_key"] != a["board_key"] and similar_titles(titles[i], titles[j]):
                pairs.append((i, j))
    return pairs


class ImageHashes:
    """본문 이미지 주소 → sha256. 보강 캐시와 이 스크립트 전용 캐시를 쓰고, 없으면 내려받는다."""

    def __init__(self, enrichment_cache: Path, path: Path, downloader: ContentAssetDownloader | None) -> None:
        assets = json.loads(enrichment_cache.read_text(encoding="utf-8")).get("assets", {})
        self.known = {url: e["sha256"] for url, e in assets.items() if e.get("sha256")}
        self.path = path
        self.own: dict[str, dict[str, Any]] = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        )
        self.downloader = downloader
        self.stats: Counter[str] = Counter()

    def lookup(self, url: str) -> str | None:
        return self.known.get(url) or (self.own.get(url) or {}).get("sha256")

    def fetch(self, urls: list[str], delay_seconds: float) -> None:
        todo = [u for u in urls if not self.lookup(u) and u not in self.own]
        print(f"해시를 구할 이미지 {len(urls)}개 중 새로 내려받을 이미지 {len(todo)}개")
        if self.downloader is None:
            return
        for k, url in enumerate(todo, 1):
            try:
                got = self.downloader.download(ContentAsset(type="inline_image", name="", url=url, source="content"))
                self.own[url] = {"sha256": got.sha256, "content_type": got.content_type}
                self.stats["downloaded"] += 1
            except ContentAssetDownloadError as exc:
                self.own[url] = {"error": exc.code}
                self.stats[exc.code] += 1
            if k % 100 == 0:
                self.save()
                print(f"  {k}/{len(todo)} {dict(self.stats)}")
            time.sleep(delay_seconds)
        self.save()

    def save(self) -> None:
        self.path.write_text(json.dumps(self.own, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--posts", type=Path, required=True, help="본문 복구 불가 공지를 뺀 연구 가공본")
    parser.add_argument("--enrichment-cache", type=Path, required=True)
    parser.add_argument("--image-hash-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--offline", action="store_true", help="내려받지 않고 캐시에 있는 해시만 쓴다")
    parser.add_argument("--delay", type=float, default=0.2, help="이미지 요청 사이 대기(초)")
    args = parser.parse_args(argv)

    posts = [p for p in json.loads(args.posts.read_text(encoding="utf-8")) if parse_published_date(p.get("published_at"))]
    posts.sort(key=lambda p: p["published_at"])
    bodies = [body_for_similarity(p.get("content") or "") for p in posts]

    rows = []
    for i, j in candidate_pairs(posts):
        a, b = posts[i], posts[j]
        sim = body_similarity(bodies[i], bodies[j])
        if same_attachment_set(a, b):
            step = ATTACHMENT_RULE
        elif sim is not None and sim >= BODY_AUTO_MERGE:
            step = BODY_RULE
        else:
            step = NEEDS_JUDGMENT
        rows.append({"i": i, "j": j, "sim": sim, "step": step})

    settings = get_settings()
    downloader = None if args.offline else ContentAssetDownloader(
        allowed_domains=settings.content_enrichment_allowed_domain_list,
        max_file_bytes=settings.content_enrichment_max_file_bytes,
    )
    hashes = ImageHashes(args.enrichment_cache, args.image_hash_cache, downloader)
    pending = [r for r in rows if r["step"] == NEEDS_JUDGMENT]
    both_have_images = [r for r in pending if body_image_urls(posts[r["i"]]) and body_image_urls(posts[r["j"]])]
    urls = list(dict.fromkeys(u for r in both_have_images for k in ("i", "j") for u in body_image_urls(posts[r[k]])))
    hashes.fetch(urls, args.delay)
    for r in both_have_images:
        if same_body_image_set(posts[r["i"]], posts[r["j"]], hashes.lookup):
            r["step"] = IMAGE_RULE

    counts = Counter(r["step"] for r in rows)
    judgment_bins = Counter(similarity_bin(r["sim"]) for r in rows if r["step"] == NEEDS_JUDGMENT)
    unknown = sum(1 for u in urls if not hashes.lookup(u))
    summary = {
        "posts": len(posts),
        "candidate_pairs": len(rows),
        "steps": {s: counts[s] for s in (ATTACHMENT_RULE, BODY_RULE, IMAGE_RULE, NEEDS_JUDGMENT)},
        "needs_judgment_by_body_similarity": dict(sorted(judgment_bins.items())),
        "image_rule": {
            "pairs_checked": len(both_have_images),
            "images": len(urls),
            "images_without_hash": unknown,
            "download": dict(hashes.stats),
        },
    }
    out_pairs = [
        {
            "a_url": posts[r["i"]]["original_url"],
            "b_url": posts[r["j"]]["original_url"],
            "a_board": posts[r["i"]]["board_key"],
            "b_board": posts[r["j"]]["board_key"],
            "a_published_at": posts[r["i"]]["published_at"],
            "b_published_at": posts[r["j"]]["published_at"],
            "title_a": posts[r["i"]]["title"],
            "title_b": posts[r["j"]]["title"],
            "body_similarity": None if r["sim"] is None else round(r["sim"], 3),
            "step": r["step"],
        }
        for r in rows
    ]
    args.output.write_text(
        json.dumps(
            {"generated_at": datetime.now().astimezone().isoformat(timespec="seconds"), "summary": summary, "pairs": out_pairs},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print("saved", args.output)


if __name__ == "__main__":
    main()
