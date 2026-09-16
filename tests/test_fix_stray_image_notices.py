"""scripts/fix_stray_image_notices.py 패치 적용 검증."""

from __future__ import annotations

import json

from scripts.fix_stray_image_notices import apply_patches, main


def _post(url: str, content: str, **extra) -> dict:
    return {"original_url": url, "title": "공지", "content": content, "content_assets": [{"url": "https://kau.ac.kr/other.jpg"}], **extra}


def test_replaces_body_and_drops_stale_enrichment() -> None:
    posts = [
        _post("https://kau.ac.kr/a", "본문\n![](https://kau.ac.kr/other.jpg)", content_enrichment={"status": "success"}),
        _post("https://kau.ac.kr/b", "그대로 두는 공지"),
    ]
    patches = [{"url": "https://kau.ac.kr/a", "title": "고칠 공지", "reason": "본문에 다른 글 이미지", "content": "본문", "content_assets": []}]

    results = apply_patches(posts, patches)

    assert [r["status"] for r in results] == ["바꿈"]
    assert results[0]["enrichment_dropped"] is True
    assert (posts[0]["content"], posts[0]["content_assets"]) == ("본문", [])
    assert "content_enrichment" not in posts[0]
    assert posts[1]["content"] == "그대로 두는 공지"


def test_reports_already_fixed_and_missing_notice() -> None:
    posts = [_post("https://kau.ac.kr/a", "본문")]
    patches = [
        {"url": "https://kau.ac.kr/a", "title": "이미 고쳐진 공지", "content": "본문", "content_assets": []},
        {"url": "https://kau.ac.kr/gone", "title": "없는 공지", "content": "본문", "content_assets": []},
    ]

    assert [r["status"] for r in apply_patches(posts, patches)] == ["이미 고쳐짐", "공지 없음"]


def test_preview_does_not_touch_the_file(tmp_path) -> None:
    notices = tmp_path / "posts.json"
    notices.write_text(json.dumps([_post("https://kau.ac.kr/a", "옛 본문")], ensure_ascii=False), encoding="utf-8")
    patch = tmp_path / "patch.json"
    patch.write_text(
        json.dumps({"patches": [{"url": "https://kau.ac.kr/a", "title": "공지", "content": "새 본문", "content_assets": []}]}),
        encoding="utf-8",
    )
    before = notices.read_text(encoding="utf-8")

    main(["--notices", str(notices), "--patch", str(patch)])
    assert notices.read_text(encoding="utf-8") == before

    main(["--notices", str(notices), "--patch", str(patch), "--apply"])
    assert json.loads(notices.read_text(encoding="utf-8"))[0]["content"] == "새 본문"
    assert [p.name for p in tmp_path.glob("posts.json.bak-*")]
