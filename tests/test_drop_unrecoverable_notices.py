"""scripts/research/drop_unrecoverable_notices.py 제외 기준 검증 — 네트워크·OpenAI 호출 없음."""

from __future__ import annotations

import json
from types import SimpleNamespace

from scripts.research import drop_unrecoverable_notices as drop
from scripts.research.enrich_cache import EnrichmentCache, build_service

SETTINGS = SimpleNamespace(
    content_enrichment_min_text_length=30,
    content_enrichment_max_assets_per_notice=3,
    content_enrichment_provider="openai",
    content_enrichment_model="fake-model",
)
TEXT = "신청 기간은 9월 1일부터 9월 5일까지이며 학과 사무실로 제출합니다. 문의는 행정실로 해 주세요."


def _post(key: str, content: str, *, image: bool = True, group: str | None = None, **extra) -> dict:
    return {
        "original_url": f"https://kau.ac.kr/notice/{key}",
        "title": f"공지 {key}",
        "published_at": "2024-03-01",
        "board_key": "general_notice",
        "content": content,
        "content_assets": [{"type": "inline_image", "url": f"https://kau.ac.kr/{key}.png"}] if image else [],
        "crosspost_group_id": group,
        **extra,
    }


def test_drops_only_image_only_notices_whose_text_could_not_be_extracted(tmp_path) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "version": 1,
                "assets": {"https://kau.ac.kr/dead.png": {"type": "inline_image", "error": "image_text_too_short"}},
                "notices": {},
            }
        ),
        encoding="utf-8",
    )
    cache = EnrichmentCache(cache_path)
    service = build_service(SETTINGS, cache)
    posts = [
        _post("dead", "**[이미지 본문]** 텍스트 본문 없음 (이미지 1개)", group="xp-00001"),  # 이미지뿐, 추출 실패 → 제외
        _post("partner", TEXT, image=False, group="xp-00001"),  # 같은 그룹의 텍스트 공지 → 남고 그룹은 비움
        _post("broken-but-text", TEXT + "\n![포스터](https://kau.ac.kr/broken-but-text.png)"),  # 이미지 깨져도 텍스트 있음
        _post("enriched", "## 보강된 본문\n\n" + TEXT, content_original=""),  # 보강 성공
        _post("title-only", "", image=False, content_empty=True),  # 사이트 원문이 제목뿐, 보강 대상 아님
    ]

    kept, removed, cleared = drop.split_unrecoverable(posts, service, cache)

    assert [r["original_url"].rsplit("/", 1)[-1] for r in removed] == ["dead"]
    assert removed[0]["assets"] == [
        {"type": "inline_image", "url": "https://kau.ac.kr/dead.png", "extracted": False, "cached_error": "image_text_too_short"}
    ]
    assert [p["original_url"].rsplit("/", 1)[-1] for p in kept] == ["partner", "broken-but-text", "enriched", "title-only"]
    assert cleared == 1
    assert kept[0]["crosspost_group_id"] is None
    assert posts[1]["crosspost_group_id"] == "xp-00001"  # 입력은 바꾸지 않는다
