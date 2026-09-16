"""scripts/research/enrich_cache.py 보강 캐시 검증 — 네트워크·OpenAI 호출 없음.

운영 보강 서비스에 가짜 provider·downloader를 끼워 한도만큼만 호출하는지, 캐시로 다시 호출하지
않는지, 원본을 바꾸지 않는지 본다.
"""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from app.crawler.services.content_asset_downloader import DownloadedAsset
from app.crawler.services.content_extractors.hwp_extractor import ExtractedText
from app.crawler.services.content_extractors.openai_provider import (
    GeneratedContent,
    OpenAIProviderError,
)
from scripts.research import enrich_cache

SETTINGS = SimpleNamespace(
    content_enrichment_min_text_length=30,
    content_enrichment_max_assets_per_notice=3,
    content_enrichment_provider="openai",
    content_enrichment_model="fake-model",
)
EXTRACTED = "2026학년도 2학기 공모전 안내. 신청 기간은 9월 1일부터 9월 5일까지이며 학과 사무실로 제출합니다."


class FakeProvider:
    def __init__(self, short_image_urls: set[str] | None = None) -> None:
        self.short_image_urls = short_image_urls or set()
        self.image_calls: list[str] = []
        self.generate_calls: list[str] = []

    def extract_image_text(self, downloaded, *, notice_meta, min_text_length) -> ExtractedText:
        self.image_calls.append(downloaded.asset.url)
        if downloaded.asset.url in self.short_image_urls:
            raise OpenAIProviderError("image_text_too_short", "extracted image text is too short")
        return ExtractedText(text=EXTRACTED, format="image", method="openai:fake-model")

    def generate_notice_content(self, *, notice_meta, extracted_texts) -> GeneratedContent:
        self.generate_calls.append(notice_meta["original_url"])
        return GeneratedContent(
            content=f"## {notice_meta['title']}\n\n{extracted_texts[0].text}",
            confidence="high",
            model="fake-model",
        )


class FakeDownloader:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def download(self, asset) -> DownloadedAsset:
        self.urls.append(asset.url)
        return DownloadedAsset(asset=asset, data=b"png", content_type="image/png", sha256=f"sha-{asset.url}")


def _poster(number: int) -> dict:
    return {
        "original_url": f"https://kau.ac.kr/notice/{number}",
        "title": f"포스터 공지 {number}",
        "content": "",
        "published_at": "2026-09-01",
        "content_assets": [{"type": "inline_image", "url": f"https://kau.ac.kr/poster{number}.png"}],
    }


def _posts() -> list[dict]:
    text_notice = {"original_url": "https://kau.ac.kr/notice/text", "title": "텍스트 공지", "content": EXTRACTED}
    return [_poster(1), _poster(2), text_notice]


def test_run_calls_api_only_up_to_limit_and_leaves_input_untouched(tmp_path) -> None:
    cache = enrich_cache.EnrichmentCache(tmp_path / "cache.json")
    provider, downloader = FakeProvider(), FakeDownloader()
    service = enrich_cache.build_service(SETTINGS, cache, provider=provider, downloader=downloader)
    posts = _posts()
    original = copy.deepcopy(posts)

    work, summary = enrich_cache.run(posts, cache, service, limit=1, seed=None, offline=False)

    assert posts == original
    assert summary == {
        "targets": 2,
        "cached_notices": 0,
        "api_notices": 1,
        "remaining_misses": 1,
        "attempted": 1,
        "succeeded": 1,
        "failed": 0,
        "error_codes": {},
    }
    assert work[0]["content"].startswith("## 포스터 공지 1")
    assert (work[0]["content_original"], work[0]["content_enrichment"]["status"]) == ("", "success")
    assert work[1]["content"] == ""  # 한도 밖 공지는 손대지 않는다
    assert (provider.image_calls, provider.generate_calls) == (
        ["https://kau.ac.kr/poster1.png"],
        ["https://kau.ac.kr/notice/1"],
    )

    saved = json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))
    assert saved["assets"]["https://kau.ac.kr/poster1.png"] | {"extracted_at": None} == {
        "type": "inline_image",
        "sha256": "sha-https://kau.ac.kr/poster1.png",
        "content_type": "image/png",
        "text": EXTRACTED,
        "format": "image",
        "method": "openai:fake-model",
        "confidence": "medium",
        "warnings": [],
        "extracted_at": None,
    }
    assert list(saved["notices"]) == ["https://kau.ac.kr/notice/1"]


def test_offline_run_applies_cache_without_download_or_api(tmp_path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = enrich_cache.EnrichmentCache(cache_path)
    online = enrich_cache.build_service(SETTINGS, cache, provider=FakeProvider(), downloader=FakeDownloader())
    first, _ = enrich_cache.run(_posts(), cache, online, limit=1, seed=None, offline=False)

    reloaded = enrich_cache.EnrichmentCache(cache_path)
    offline = enrich_cache.build_service(SETTINGS, reloaded)
    work, summary = enrich_cache.run(_posts(), reloaded, offline, limit=None, seed=None, offline=True)

    assert work[0]["content"] == first[0]["content"]
    assert work[1]["content"] == ""
    assert (summary["cached_notices"], summary["api_notices"], summary["succeeded"]) == (1, 0, 1)


def test_deterministic_image_failure_is_not_paid_twice(tmp_path) -> None:
    cache = enrich_cache.EnrichmentCache(tmp_path / "cache.json")
    provider = FakeProvider(short_image_urls={"https://kau.ac.kr/poster1.png"})
    service = enrich_cache.build_service(SETTINGS, cache, provider=provider, downloader=FakeDownloader())
    posts = [_poster(1)]

    _, first = enrich_cache.run(posts, cache, service, limit=1, seed=None, offline=False)
    _, second = enrich_cache.run(posts, cache, service, limit=1, seed=None, offline=False)

    assert first["error_codes"] == second["error_codes"] == {"no_extracted_text": 1}
    assert provider.image_calls == ["https://kau.ac.kr/poster1.png"]
    assert provider.generate_calls == []


@pytest.mark.parametrize(
    "extra_args",
    [
        ["--output", "SAME"],  # 입력을 덮어쓰려는 경우
        [],  # 호출하는 실행인데 --limit 이 없는 경우
    ],
)
def test_main_refuses_overwrite_and_unbounded_paid_run(tmp_path, extra_args) -> None:
    raw = tmp_path / "raw.json"
    raw.write_text("[]", encoding="utf-8")
    args = ["--input", str(raw), "--cache", str(tmp_path / "cache.json")]
    args += [str(raw) if value == "SAME" else value for value in extra_args]
    if extra_args:
        args.append("--offline")

    with pytest.raises(SystemExit):
        enrich_cache.main(args)
