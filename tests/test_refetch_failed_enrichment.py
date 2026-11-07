"""scripts/refetch_failed_enrichment.py 다시 읽기 반영 검증 (네트워크 없이 fetch 를 바꿔 끼운다)."""

from __future__ import annotations

import json

from scripts.refetch_failed_enrichment import refetch_posts, run, select_targets

BROKEN = [{"type": "inline_image", "name": "inline-image-1", "url": "data:image/png;base64,iVBO/broken"}]
FIXED = [{"type": "inline_image", "name": "inline-image-1", "url": "data:image/png;base64,iVBO//fixed"}]


def _post(url: str, **extra) -> dict:
    return {
        "original_url": url,
        "title": "공지",
        "content": "**[이미지 본문]** 텍스트 본문 없음 (이미지 1개)",
        "content_hash": "old",
        "content_assets": BROKEN,
        "content_enrichment": {"status": "failed", "error_code": "no_extracted_text"},
        **extra,
    }


def _fresh(url: str, assets: list[dict] | None, content_hash: str = "new") -> dict:
    fresh = {"original_url": url, "title": "공지", "content": "**[이미지 본문]** 텍스트 본문 없음 (이미지 1개)", "content_hash": content_hash}
    if assets is not None:
        fresh["content_assets"] = assets
    return fresh


def test_selects_failed_enrichment_or_given_urls() -> None:
    posts = [_post("a"), _post("b", content_enrichment={"status": "success"}), _post("c", content_enrichment=None)]

    assert [p["original_url"] for p in select_targets(posts, [])] == ["a"]
    assert [p["original_url"] for p in select_targets(posts, ["c"])] == ["c"]


def test_replaces_broken_assets_and_drops_failed_enrichment() -> None:
    post = _post("a")

    results = refetch_posts([post], lambda p: _fresh("a", FIXED))

    assert results[0]["status"] == "바꿈"
    assert post["content_assets"] == FIXED
    assert post["content_hash"] == "new"
    assert "content_enrichment" not in post


def test_same_original_is_left_alone() -> None:
    post = _post("a", content_hash="same")

    results = refetch_posts([post], lambda p: _fresh("a", BROKEN, content_hash="same"))

    assert results[0]["status"] == "같음"
    assert post["content_enrichment"]["status"] == "failed"


def test_clears_assets_when_fresh_body_has_no_image() -> None:
    post = _post("a", content_hash="same")

    refetch_posts([post], lambda p: _fresh("a", None, content_hash="same"))

    assert post["content_assets"] == []


def test_fetch_failure_keeps_post() -> None:
    post = _post("a")

    results = refetch_posts([post], lambda p: None)

    assert results[0]["status"] == "읽기 실패"
    assert post["content_assets"] == BROKEN


def test_preview_does_not_touch_the_file(tmp_path) -> None:
    path = tmp_path / "posts.json"
    path.write_text(json.dumps([_post("a")]), encoding="utf-8")
    before = path.read_text(encoding="utf-8")

    run(path, [], False, lambda p: _fresh("a", FIXED))

    assert path.read_text(encoding="utf-8") == before
    assert not list(tmp_path.glob("posts.json.bak-*"))


def test_apply_writes_file_and_backup(tmp_path) -> None:
    path = tmp_path / "posts.json"
    path.write_text(json.dumps([_post("a"), _post("b", content_enrichment={"status": "success"})]), encoding="utf-8")

    run(path, [], True, lambda p: _fresh("a", FIXED))

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved[0]["content_assets"] == FIXED
    assert saved[1]["content_enrichment"] == {"status": "success"}
    assert len(list(tmp_path.glob("posts.json.bak-*"))) == 1
