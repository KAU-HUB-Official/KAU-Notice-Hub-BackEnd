"""운영 공지 스냅샷에서 다른 글 이미지가 섞인 공지의 본문을 고친 값으로 바꾼다.

college.kau.ac.kr 상세 API는 이전·다음 글 본문도 함께 주는데, 예전 크롤러가 응답 전체에서 본문 이미지를
뽑아 이웃 글 이미지가 공지에 붙었다(2026-09-15 확인, 2026-09-16 크롤러 수정). 이미 수집해 둔 공지는 다시
수집되지 않으므로, 고친 본문을 담은 패치 파일로 스냅샷을 직접 바꾼다.

패치 파일: {"patches": [{"url", "title", "content", "content_assets", "reason"}, ...]}
- url 이 공지의 original_url 과 같은 항목을 찾아 content·content_assets 를 바꾸고, 본문이 바뀌었으므로
  옛 보강 기록(content_enrichment)은 지운다.
- 기본은 미리보기다. 실제로 바꾸려면 --apply 를 준다. 원본은 <파일>.bak-<시각> 으로 복사해 둔다.

실행 (운영 서버, 네트워크·OpenAI 호출 없음):
    python3 scripts/fix_stray_image_notices.py --notices /data/kau_official_posts.json \\
        --patch production_patch_2026-09-16.json           # 미리보기
    python3 scripts/fix_stray_image_notices.py --notices /data/kau_official_posts.json \\
        --patch production_patch_2026-09-16.json --apply   # 반영
그다음 DB를 다시 만든다: rm -f /data/kau_notice_hub.db /data/kau_notice_hub.db.lock
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

FIELDS = ("content", "content_assets")


def apply_patches(posts: list[dict[str, Any]], patches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """posts 를 제자리에서 고치고, 패치별 결과(status)를 돌려준다."""
    by_url = {str(post.get("original_url") or ""): post for post in posts}
    results = []
    for patch in patches:
        url = str(patch.get("url") or "")
        post = by_url.get(url)
        if post is None:
            results.append({**_label(patch), "status": "공지 없음"})
            continue
        if (post.get("content") or "") == (patch.get("content") or ""):
            results.append({**_label(patch), "status": "이미 고쳐짐"})
            continue
        results.append(
            {
                **_label(patch),
                "status": "바꿈",
                "before_chars": len(post.get("content") or ""),
                "after_chars": len(patch.get("content") or ""),
                "enrichment_dropped": "content_enrichment" in post,
            }
        )
        for field in FIELDS:
            post[field] = patch.get(field) or ("" if field == "content" else [])
        post.pop("content_enrichment", None)
    return results


def _label(patch: dict[str, Any]) -> dict[str, Any]:
    return {"url": str(patch.get("url") or ""), "title": str(patch.get("title") or ""), "reason": patch.get("reason", "")}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--notices", type=Path, required=True, help="운영 공지 스냅샷 JSON (NOTICE_JSON_PATH)")
    parser.add_argument("--patch", type=Path, required=True, help="고친 본문을 담은 패치 JSON")
    parser.add_argument("--apply", action="store_true", help="실제로 파일을 바꾼다. 없으면 미리보기만 한다")
    args = parser.parse_args(argv)

    posts = json.loads(args.notices.read_text(encoding="utf-8"))
    patch_doc = json.loads(args.patch.read_text(encoding="utf-8"))
    patches = patch_doc["patches"] if isinstance(patch_doc, dict) else patch_doc
    results = apply_patches(posts, patches)

    changed = [r for r in results if r["status"] == "바꿈"]
    for r in results:
        head = f"  {r['status']:<8} | {r['reason'][:16]:<16} | {r['title'][:40]}"
        print(head + (f" | {r['before_chars']}자 → {r['after_chars']}자" if r["status"] == "바꿈" else ""))
    print(
        json.dumps(
            {
                "패치": len(results),
                "바꿈": len(changed),
                "이미 고쳐짐": sum(1 for r in results if r["status"] == "이미 고쳐짐"),
                "공지 없음": sum(1 for r in results if r["status"] == "공지 없음"),
            },
            ensure_ascii=False,
        )
    )
    if not args.apply:
        print("미리보기입니다. 반영하려면 --apply 를 주세요.")
        return
    if not changed:
        print("바꿀 공지가 없어 파일을 건드리지 않았습니다.")
        return

    backup = args.notices.with_name(f"{args.notices.name}.bak-{datetime.now().strftime('%Y%m%d%H%M%S')}")
    backup.write_bytes(args.notices.read_bytes())
    with tempfile.NamedTemporaryFile(
        "w", dir=args.notices.parent, prefix=f".{args.notices.name}.", suffix=".tmp", delete=False, encoding="utf-8"
    ) as tmp:
        json.dump(posts, tmp, ensure_ascii=False, indent=2)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, args.notices)
    print(f"반영했습니다. 원본 복사본: {backup}")
    print("DB를 다시 만들려면: rm -f /data/kau_notice_hub.db /data/kau_notice_hub.db.lock")


if __name__ == "__main__":
    main()
