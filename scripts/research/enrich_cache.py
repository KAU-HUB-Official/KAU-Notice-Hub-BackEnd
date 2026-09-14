"""연구 가공본용 본문 보강(이미지·HWP)을 캐시와 함께 실행한다.

운영 크롤러 보강(ContentEnrichmentService)과 같은 코드 경로를 쓰되, 다운로더·추출기·본문 생성기를
캐시를 거치는 구현으로 바꿔 끼운다. 결과는 원본 공지에 쓰지 않고 캐시 파일에 쌓으며, 가공본은
입력 사본에 적용해 따로 쓴다. 재수집해도 같은 이미지·첨부 URL은 다시 호출하지 않는다.

캐시(JSON)
- assets[자산 URL]: 파일 해시·추출 텍스트·방식(모델)·처리 시각. 같은 파일이면 다시 해도 같은 실패
  (DETERMINISTIC_ERRORS)도 error로 남겨 비용을 다시 쓰지 않는다.
- notices[공지 URL]: 추출 텍스트 묶음 해시(inputs_sha256)와 생성한 본문·신뢰도·모델·처리 시각.
  추출 텍스트가 바뀌면 다시 생성한다.
모델 설정이 바뀌어도 캐시 항목을 무효화하지 않는다. 항목마다 방식(모델)이 남아 있으니 필요하면 걸러 쓴다.

실행 기록은 캐시 옆 <캐시 이름>.runs.jsonl 에 한 줄씩 남긴다(선택·성공·실패 수, 모델별 호출·토큰).

예:
    # 캐시에 없는 보강 대상 중 50건만 무작위로 골라 호출 (OpenAI 비용 발생)
    .venv/bin/python -m scripts.research.enrich_cache \\
        --input data/research/kau_notices_marked_<수집일>.json \\
        --cache data/research/enrichment_cache.json --limit 50 --seed 20260915
    # 호출·다운로드 없이 캐시만 적용해 가공본 작성
    .venv/bin/python -m scripts.research.enrich_cache \\
        --input data/research/kau_notices_marked_<수집일>.json \\
        --cache data/research/enrichment_cache.json --offline \\
        --output data/research/kau_notices_enriched_<수집일>.json
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import random
import tempfile
import time
from collections import defaultdict
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.crawler.services.content_asset_downloader import (
    ContentAsset,
    ContentAssetDownloadError,
    ContentAssetDownloader,
    DownloadedAsset,
)
from app.crawler.services.content_enrichment_service import (
    ContentEnrichmentRunResult,
    ContentEnrichmentService,
)
from app.crawler.services.content_extractors.hwp_extractor import (
    ExtractedText,
    HwpTextExtractionError,
    HwpTextExtractor,
)
from app.crawler.services.content_extractors.openai_provider import (
    GeneratedContent,
    OpenAIContentProvider,
    OpenAIProviderError,
)

CACHE_VERSION = 1
# 같은 파일이면 다시 시도해도 결과가 같은 실패. 전송 오류나 로컬 도구 부재(hwp_text_extract_failed)는
# 환경에 따라 달라지므로 캐시하지 않는다.
DETERMINISTIC_ERRORS = frozenset(
    {"image_text_too_short", "unsupported_hwp_format", "hwp_text_too_short"}
)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class EnrichmentCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if data and data.get("version") != CACHE_VERSION:
            raise ValueError(f"캐시 버전이 다릅니다: {path} version={data.get('version')}")
        self.assets: dict[str, dict[str, Any]] = data.get("assets", {})
        self.notices: dict[str, dict[str, Any]] = data.get("notices", {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": CACHE_VERSION, "assets": self.assets, "notices": self.notices}
        fd, tmp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=1)
        os.replace(tmp_name, self.path)


def _cached_text(entry: dict[str, Any], error_cls: type[Exception]) -> ExtractedText:
    if entry.get("error"):
        raise error_cls(entry["error"], "cached deterministic failure")
    return ExtractedText(
        text=entry["text"],
        format=entry["format"],
        method=entry["method"],
        confidence=entry.get("confidence", "medium"),
        warnings=list(entry.get("warnings") or []),
    )


def _asset_entry(downloaded: DownloadedAsset) -> dict[str, Any]:
    return {
        "type": downloaded.asset.type,
        "sha256": downloaded.sha256,
        "content_type": downloaded.content_type,
        "extracted_at": _now(),
    }


class CachedDownloader:
    """캐시에 있는 자산은 내려받지 않는다. downloader가 None이면 캐시에 없는 자산은 실패시킨다."""

    def __init__(self, downloader: ContentAssetDownloader | None, cache: EnrichmentCache) -> None:
        self.downloader = downloader
        self.cache = cache

    def download(self, asset: ContentAsset) -> DownloadedAsset:
        cached = self.cache.assets.get(asset.url)
        if cached is not None:
            return DownloadedAsset(
                asset=asset,
                data=b"",
                content_type=str(cached.get("content_type") or ""),
                sha256=str(cached.get("sha256") or ""),
            )
        if self.downloader is None:
            raise ContentAssetDownloadError("cache_miss", f"asset not cached: {asset.url}")
        return self.downloader.download(asset)


class CachedHwpExtractor:
    def __init__(self, extractor: HwpTextExtractor, cache: EnrichmentCache) -> None:
        self.extractor = extractor
        self.cache = cache

    def extract(self, downloaded: DownloadedAsset) -> ExtractedText:
        cached = self.cache.assets.get(downloaded.asset.url)
        if cached is not None:
            return _cached_text(cached, HwpTextExtractionError)
        try:
            extracted = self.extractor.extract(downloaded)
        except HwpTextExtractionError as exc:
            if exc.code in DETERMINISTIC_ERRORS:
                self.cache.assets[downloaded.asset.url] = {**_asset_entry(downloaded), "error": exc.code}
            raise
        self.cache.assets[downloaded.asset.url] = {**_asset_entry(downloaded), **asdict(extracted)}
        return extracted


class CachedImageExtractor:
    def __init__(self, provider: OpenAIContentProvider | None, cache: EnrichmentCache) -> None:
        self.provider = provider
        self.cache = cache

    def extract_image_text(
        self,
        downloaded: DownloadedAsset,
        *,
        notice_meta: dict,
        min_text_length: int,
    ) -> ExtractedText:
        cached = self.cache.assets.get(downloaded.asset.url)
        if cached is not None:
            return _cached_text(cached, OpenAIProviderError)
        if self.provider is None:
            raise OpenAIProviderError("cache_miss", f"asset not cached: {downloaded.asset.url}")
        try:
            extracted = self.provider.extract_image_text(
                downloaded,
                notice_meta=notice_meta,
                min_text_length=min_text_length,
            )
        except OpenAIProviderError as exc:
            if exc.code in DETERMINISTIC_ERRORS:
                self.cache.assets[downloaded.asset.url] = {**_asset_entry(downloaded), "error": exc.code}
            raise
        self.cache.assets[downloaded.asset.url] = {**_asset_entry(downloaded), **asdict(extracted)}
        return extracted


class CachedContentGenerator:
    def __init__(self, provider: OpenAIContentProvider | None, cache: EnrichmentCache) -> None:
        self.provider = provider
        self.cache = cache

    def generate_notice_content(
        self,
        *,
        notice_meta: dict,
        extracted_texts: list[ExtractedText],
    ) -> GeneratedContent:
        url = str(notice_meta.get("original_url") or "")
        inputs_sha256 = hashlib.sha256(
            json.dumps([[item.method, item.text] for item in extracted_texts], ensure_ascii=False).encode(
                "utf-8"
            )
        ).hexdigest()
        cached = self.cache.notices.get(url)
        if cached is not None and cached.get("inputs_sha256") == inputs_sha256:
            return GeneratedContent(
                **{item.name: cached[item.name] for item in fields(GeneratedContent)}
            )
        if self.provider is None:
            raise OpenAIProviderError("cache_miss", f"notice not cached: {url}")
        generated = self.provider.generate_notice_content(
            notice_meta=notice_meta,
            extracted_texts=extracted_texts,
        )
        self.cache.notices[url] = {
            "inputs_sha256": inputs_sha256,
            **asdict(generated),
            "generated_at": _now(),
        }
        return generated


def build_service(
    settings: Any,
    cache: EnrichmentCache,
    *,
    provider: OpenAIContentProvider | None = None,
    downloader: ContentAssetDownloader | None = None,
    hwp_extractor: HwpTextExtractor | None = None,
) -> ContentEnrichmentService:
    """운영 보강 설정·코드 경로에 캐시를 끼운 서비스. provider·downloader가 없으면 캐시만 쓴다."""
    return ContentEnrichmentService(
        enabled=True,
        min_text_length=settings.content_enrichment_min_text_length,
        max_assets_per_notice=settings.content_enrichment_max_assets_per_notice,
        # 서비스 호출 예산은 캐시 적중도 한 번으로 세므로 쓰지 않고, 호출 대상 공지 수(limit)로 막는다.
        max_calls_per_run=10**9,
        downloader=CachedDownloader(downloader, cache),
        hwp_extractor=CachedHwpExtractor(
            hwp_extractor
            or HwpTextExtractor(min_text_length=settings.content_enrichment_min_text_length),
            cache,
        ),
        image_extractor=CachedImageExtractor(provider, cache),
        content_generator=CachedContentGenerator(provider, cache),
        provider_name=settings.content_enrichment_provider,
        model_name=settings.content_enrichment_model,
    )


def run(
    posts: list[dict[str, Any]],
    cache: EnrichmentCache,
    service: ContentEnrichmentService,
    *,
    limit: int | None,
    seed: int | None,
    offline: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """posts 사본에 보강을 적용해 돌려준다. posts 자체는 바꾸지 않는다.

    캐시에 생성 본문이 있는 공지는 모두 적용하고, 캐시에 없는 공지는 offline이 아니면 limit건까지만
    호출한다(seed가 있으면 무작위로 고른다). 공지 하나를 마칠 때마다 캐시를 저장해 중단돼도 쓴
    비용이 남는다.
    """
    work = copy.deepcopy(posts)
    targets = [post for post in work if service.should_enrich(post)]
    cached = [post for post in targets if str(post.get("original_url") or "") in cache.notices]
    misses = [post for post in targets if str(post.get("original_url") or "") not in cache.notices]
    if seed is not None:
        random.Random(seed).shuffle(misses)
    selected_misses = [] if offline else misses[: len(misses) if limit is None else limit]

    totals = ContentEnrichmentRunResult()
    for post in cached + selected_misses:
        result = service.enrich_posts([post])
        totals.target_count += result.target_count
        totals.attempted += result.attempted
        totals.succeeded += result.succeeded
        totals.failed += result.failed
        totals.skipped += result.skipped
        cache.save()

    summary = {
        "targets": len(targets),
        "cached_notices": len(cached),
        "api_notices": len(selected_misses),
        "remaining_misses": len(misses) - len(selected_misses),
        "attempted": totals.attempted,
        "succeeded": totals.succeeded,
        "failed": totals.failed,
        "error_codes": dict(
            sorted(
                _count(
                    post["content_enrichment"].get("error_code")
                    for post in cached + selected_misses
                    if (post.get("content_enrichment") or {}).get("status") == "failed"
                ).items()
            )
        ),
    }
    return work, summary


def _count(values: Any) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        counts[str(value)] += 1
    return counts


def track_usage(provider: OpenAIContentProvider) -> dict[str, dict[str, int]]:
    """provider의 HTTP 호출을 감싸 모델별 호출 수와 토큰 사용량을 모은다."""
    usage: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "calls": 0,
            "http_errors": 0,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
        }
    )
    original_post = provider.session.post

    def counting_post(url: str, *, json: dict | None = None, **kwargs: Any):  # noqa: A002
        response = original_post(url, json=json, **kwargs)
        entry = usage[str((json or {}).get("model"))]
        entry["calls"] += 1
        entry["http_errors"] += int(response.status_code >= 400)
        try:
            data = response.json()
        except ValueError:
            data = {}
        tokens = (data.get("usage") if isinstance(data, dict) else None) or {}
        entry["input_tokens"] += int(tokens.get("input_tokens") or 0)
        entry["cached_input_tokens"] += int(
            (tokens.get("input_tokens_details") or {}).get("cached_tokens") or 0
        )
        entry["output_tokens"] += int(tokens.get("output_tokens") or 0)
        entry["reasoning_tokens"] += int(
            (tokens.get("output_tokens_details") or {}).get("reasoning_tokens") or 0
        )
        return response

    provider.session.post = counting_post
    return usage


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="연구 가공본용 본문 보강을 캐시와 함께 실행한다.")
    parser.add_argument("--input", type=Path, required=True, help="보강할 공지 JSON (원본 또는 가공본)")
    parser.add_argument("--cache", type=Path, required=True, help="보강 캐시 JSON")
    parser.add_argument("--output", type=Path, default=None, help="보강을 적용한 가공본 JSON (선택)")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="캐시에 없는 공지 중 이번에 호출할 최대 공지 수. 호출하는 실행에는 반드시 지정",
    )
    parser.add_argument("--seed", type=int, default=None, help="호출할 공지를 무작위로 고를 때 시드")
    parser.add_argument("--offline", action="store_true", help="호출·다운로드 없이 캐시만 적용")
    args = parser.parse_args(argv)

    if args.output is not None and args.output.resolve() == args.input.resolve():
        parser.error("입력 파일을 덮어쓰지 않습니다. --output 을 다른 경로로 주세요.")
    if not args.offline and args.limit is None:
        parser.error("OpenAI 비용이 드는 실행입니다. --limit 으로 호출할 공지 수를 정하세요.")

    settings = get_settings()
    cache = EnrichmentCache(args.cache)
    provider: OpenAIContentProvider | None = None
    downloader: ContentAssetDownloader | None = None
    usage: dict[str, dict[str, int]] = {}
    if not args.offline:
        if not settings.openai_api_key:
            parser.error("OPENAI_API_KEY 가 필요합니다.")
        provider = OpenAIContentProvider(
            api_key=settings.openai_api_key,
            model=settings.content_enrichment_model,
            fallback_model=settings.content_enrichment_fallback_model,
            image_detail=settings.content_enrichment_image_detail,
        )
        usage = track_usage(provider)
        downloader = ContentAssetDownloader(
            allowed_domains=settings.content_enrichment_allowed_domain_list,
            max_file_bytes=settings.content_enrichment_max_file_bytes,
        )
    service = build_service(settings, cache, provider=provider, downloader=downloader)

    started_at = _now()
    started = time.monotonic()
    posts = json.loads(args.input.read_text(encoding="utf-8"))
    work, summary = run(posts, cache, service, limit=args.limit, seed=args.seed, offline=args.offline)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(work, ensure_ascii=False, indent=2), encoding="utf-8")

    record = {
        "started_at": started_at,
        "finished_at": _now(),
        "seconds": round(time.monotonic() - started, 1),
        "input": str(args.input),
        "cache": str(args.cache),
        "output": str(args.output) if args.output else None,
        "offline": args.offline,
        "limit": args.limit,
        "seed": args.seed,
        "settings": {
            "model": settings.content_enrichment_model,
            "fallback_model": settings.content_enrichment_fallback_model,
            "image_detail": settings.content_enrichment_image_detail,
            "max_assets_per_notice": settings.content_enrichment_max_assets_per_notice,
            "min_text_length": settings.content_enrichment_min_text_length,
        },
        "summary": summary,
        "usage_by_model": dict(usage),
    }
    runs_path = args.cache.with_name(f"{args.cache.stem}.runs.jsonl")
    with runs_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
