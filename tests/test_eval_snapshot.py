"""평가용 고정 스냅샷 생성·로드 검증 — 네트워크·OpenAI 호출 없음."""

from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest

from app.sqlite_repository import SqliteNoticeRepository
from tests.eval import snapshot as snap

REFERENCE = date(2026, 9, 14)
CUTOFF = date(2023, 9, 1)
LONG_TEXT = "본문 내용이 충분히 긴 일반 공지입니다. 신청 기간과 방법, 제출 서류를 자세히 안내합니다."


def _post(post_id: str, published_at: str, *, permanent: bool = False, **extra) -> dict:
    return {
        "id": post_id,
        "title": f"공지 {post_id}",
        "content": LONG_TEXT,
        "published_at": published_at,
        "is_permanent_notice": permanent,
        **extra,
    }


def _write_posts(root, posts) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / snap.POSTS_FILE).write_text(json.dumps(posts, ensure_ascii=False), encoding="utf-8")


def test_build_keeps_cutoff_day_and_permanent_notices(tmp_path) -> None:
    root = tmp_path / "snapshot-test"
    _write_posts(
        root,
        [
            _post("recent", "2026-09-01"),
            _post("on-cutoff", "2023-09-01"),
            _post("before-cutoff", "2023-08-31"),
            _post("old-permanent", "2020-03-02", permanent=True),
        ],
    )

    manifest = snap.build_snapshot(root, reference_date=REFERENCE, cutoff_date=CUTOFF)

    assert (
        manifest["posts_crawled"],
        manifest["posts_pruned_before_cutoff"],
        manifest["posts_kept"],
        manifest["permanent_notices"],
        manifest["notices_in_db"],
    ) == (4, 1, 3, 1, 3)
    assert manifest["general_published_range"] == ["2023-09-01", "2026-09-01"]
    assert [p["title"] for p in manifest["pruned_posts"]] == ["공지 before-cutoff"]
    # 적재용 임시 파일은 남기지 않는다.
    assert sorted(p.name for p in root.iterdir()) == [snap.DB_FILE, snap.MANIFEST_FILE, snap.POSTS_FILE]


def test_build_counts_image_only_notices_as_enrichment_targets(tmp_path) -> None:
    root = tmp_path / "snapshot-test"
    poster = _post(
        "poster",
        "2026-09-01",
        content="",
        content_assets=[{"type": "inline_image", "url": "https://kau.ac.kr/poster.png"}],
    )
    _write_posts(root, [poster, _post("text", "2026-09-02")])

    manifest = snap.build_snapshot(root, reference_date=REFERENCE, cutoff_date=CUTOFF)

    assert manifest["enrichment_targets"] == 1
    assert manifest["enrichment_target_assets"] == {"inline_image": 1}


def test_build_reads_research_raw_without_copying_it(tmp_path) -> None:
    research_dir = tmp_path / "research"
    research_dir.mkdir()
    raw = research_dir / "kau_notices_raw_2026-09-15.json"
    raw.write_text(json.dumps([_post("recent", "2026-09-01")], ensure_ascii=False), encoding="utf-8")
    crawl_manifest = research_dir / "crawl_manifest_2026-09-15.json"
    crawl_manifest.write_text(json.dumps({"options": {"since": "2023-09-01"}}), encoding="utf-8")
    root = tmp_path / "snapshot-test"

    manifest = snap.build_snapshot(
        root,
        reference_date=REFERENCE,
        cutoff_date=CUTOFF,
        posts_path=raw,
        crawl_meta_path=crawl_manifest,
    )

    assert (manifest["posts_source"], manifest["posts_kept"]) == (str(raw), 1)
    assert manifest["crawl"] == {"options": {"since": "2023-09-01"}}
    assert sorted(p.name for p in root.iterdir()) == [snap.DB_FILE, snap.MANIFEST_FILE]


def test_build_rejects_cutoff_not_before_reference(tmp_path) -> None:
    root = tmp_path / "snapshot-test"
    _write_posts(root, [])
    with pytest.raises(ValueError):
        snap.build_snapshot(root, reference_date=CUTOFF, cutoff_date=REFERENCE)


def test_load_snapshot_opens_db_with_reference_date(tmp_path) -> None:
    root = tmp_path / "snapshot-test"
    _write_posts(root, [_post("recent", "2026-09-01")])
    snap.build_snapshot(root, reference_date=REFERENCE, cutoff_date=CUTOFF)

    loaded = snap.load_snapshot(root)

    assert (loaded.name, loaded.reference_date) == ("snapshot-test", REFERENCE)
    notices = asyncio.run(SqliteNoticeRepository(loaded.db_path).list_all())
    assert len(notices) == 1


def test_load_snapshot_refuses_to_fall_back_when_missing(tmp_path) -> None:
    with pytest.raises(SystemExit, match="평가용 스냅샷이 없습니다"):
        snap.load_snapshot(tmp_path / "missing")


def test_snapshot_dir_env_override(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EVAL_SNAPSHOT_DIR", str(tmp_path / "other"))
    assert snap.snapshot_dir() == tmp_path / "other"

    monkeypatch.delenv("EVAL_SNAPSHOT_DIR")
    assert snap.snapshot_dir() == snap.DEFAULT_SNAPSHOT_DIR
