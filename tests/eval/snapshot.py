"""평가용 고정 공지 스냅샷.

RAGAS 채점과 분기 검증은 운영 DB가 아니라 이 스냅샷만 읽는다. 운영 DB는 크롤링 주기마다
바뀌어, 같은 질문셋이라도 실행 시점마다 검색 후보가 달라지므로 전후 비교가 성립하지 않는다.

스냅샷 디렉터리(data/eval/<이름>/, git 제외 — 공지 원문에 학번·성명 등이 섞여 있다)
- posts.json         크롤러 원본 출력 (python -m app.crawler.main --output ...)
- crawl_meta.json    수집 시각·환경변수·커밋·재수집 기록 (선택)
- kau_notice_hub.db  posts.json 을 기준일 컷오프로 정리해 적재한 SQLite (평가 러너가 읽는다)
- manifest.json      기준일·컷오프·건수·컷오프로 뺀 공지 목록·이미지 본문 보강 대상 수

기준일(reference_date)은 평가 러너가 "오늘"로 쓴다. "이번 주 마감" 같은 질문의 정답이 실행
날짜에 따라 바뀌지 않게 하기 위함이다.

만들기:
    .venv/bin/python -m tests.eval.snapshot --reference-date 2026-09-14 --cutoff-date 2023-09-01
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

DEFAULT_SNAPSHOT_DIR = Path("data/eval/snapshot-2026-09-14")
POSTS_FILE = "posts.json"
CRAWL_META_FILE = "crawl_meta.json"
DB_FILE = "kau_notice_hub.db"
MANIFEST_FILE = "manifest.json"


@dataclass(frozen=True)
class EvalSnapshot:
    root: Path
    db_path: Path
    reference_date: date

    @property
    def name(self) -> str:
        return self.root.name


def snapshot_dir() -> Path:
    raw = os.environ.get("EVAL_SNAPSHOT_DIR", "").strip()
    return Path(raw) if raw else DEFAULT_SNAPSHOT_DIR


def load_snapshot(root: Path | None = None) -> EvalSnapshot:
    """평가 러너가 쓸 스냅샷을 연다. 없으면 운영 DB로 대신 돌리지 않고 멈춘다."""
    root = root or snapshot_dir()
    manifest_path = root / MANIFEST_FILE
    db_path = root / DB_FILE
    if not manifest_path.exists() or not db_path.exists():
        raise SystemExit(
            f"평가용 스냅샷이 없습니다: {root}\n"
            "운영 DB로 대신 평가하지 않습니다. docs/RAG_EVALUATION.md 의 '평가 데이터 스냅샷' 절을 "
            "참고해 만들거나, EVAL_SNAPSHOT_DIR 로 다른 스냅샷을 지정하세요."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return EvalSnapshot(
        root=root,
        db_path=db_path,
        reference_date=date.fromisoformat(manifest["reference_date"]),
    )


def build_snapshot(root: Path, *, reference_date: date, cutoff_date: date) -> dict[str, Any]:
    """크롤러 원본(posts.json)을 기준일 컷오프로 정리해 DB와 manifest를 만든다.

    일반공지는 cutoff_date 이후(당일 포함) 게시분만 남기고, 상시공지는 게시일과 무관하게 남긴다.
    크롤러 보존 정책과 같은 판정(should_prune_stale_notice)을 쓰되 "오늘"을 기준일로 고정해,
    수집이 자정을 넘기거나 나중에 다시 만들어도 경계가 흔들리지 않게 한다.
    """
    # 크롤러 모듈은 import 시 로거 파일 핸들러를 붙이므로, 스냅샷을 여는 러너에는 싣지 않는다.
    from app.config import get_settings
    from app.crawler.policies.notice_policy import parse_published_date, should_prune_stale_notice
    from app.crawler.services.content_enrichment_service import ContentEnrichmentService
    from app.ingest import ingest_json_snapshot

    if cutoff_date >= reference_date:
        raise ValueError("cutoff_date 는 reference_date 보다 이전이어야 합니다.")

    posts = json.loads((root / POSTS_FILE).read_text(encoding="utf-8"))
    # should_prune_stale_notice 는 게시일 <= 기준일 - lookback 을 정리한다. cutoff_date 당일
    # 공지를 남기려면 경계를 하루 앞(cutoff_date - 1일)에 둔다.
    lookback_days = (reference_date - cutoff_date).days + 1
    kept: list[dict[str, Any]] = []
    pruned: list[dict[str, Any]] = []
    for post in posts:
        stale = should_prune_stale_notice(
            post, lookback_days=lookback_days, current_date=reference_date
        )
        (pruned if stale else kept).append(post)

    # 적재 입력은 posts.json 과 거의 같은 대용량 사본이라 임시 파일로 쓰고 지운다.
    # 무엇을 뺐는지는 manifest 의 pruned_posts 로 남긴다.
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", prefix=".ingest.", dir=root, delete=False, encoding="utf-8"
    ) as tmp:
        json.dump(kept, tmp, ensure_ascii=False)
        ingest_input = Path(tmp.name)
    try:
        ingest = ingest_json_snapshot(json_path=ingest_input, db_path=root / DB_FILE)
    finally:
        ingest_input.unlink(missing_ok=True)

    enrichment = ContentEnrichmentService.from_settings(get_settings())
    targets = [post for post in kept if enrichment.should_enrich(post)]
    target_assets = Counter(
        asset.type for post in targets for asset in enrichment.find_supported_assets(post)
    )
    general_dates = sorted(
        published
        for post in kept
        if not post.get("is_permanent_notice")
        if (published := parse_published_date(post.get("published_at")))
    )

    meta_path = root / CRAWL_META_FILE
    manifest = {
        "name": root.name,
        "reference_date": reference_date.isoformat(),
        "cutoff_date": cutoff_date.isoformat(),
        "posts_crawled": len(posts),
        "posts_pruned_before_cutoff": len(pruned),
        "posts_kept": len(kept),
        "permanent_notices": sum(1 for post in kept if post.get("is_permanent_notice")),
        "notices_in_db": ingest.total_notices,
        "general_published_range": (
            [general_dates[0].isoformat(), general_dates[-1].isoformat()]
            if general_dates
            else None
        ),
        "pruned_posts": [
            {
                "title": post.get("title"),
                "published_at": post.get("published_at"),
                "original_url": post.get("original_url"),
            }
            for post in pruned
        ],
        "enrichment_targets": len(targets),
        "enrichment_target_assets": dict(target_assets),
        "crawl": (
            json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else None
        ),
        "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    (root / MANIFEST_FILE).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="평가용 고정 공지 스냅샷을 만든다.")
    parser.add_argument(
        "--root", type=Path, default=None, help="스냅샷 디렉터리 (기본: EVAL_SNAPSHOT_DIR 또는 기본 경로)"
    )
    parser.add_argument("--reference-date", type=date.fromisoformat, required=True)
    parser.add_argument("--cutoff-date", type=date.fromisoformat, required=True)
    args = parser.parse_args(argv)

    manifest = build_snapshot(
        args.root or snapshot_dir(),
        reference_date=args.reference_date,
        cutoff_date=args.cutoff_date,
    )
    summary = {key: value for key, value in manifest.items() if key != "crawl"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
