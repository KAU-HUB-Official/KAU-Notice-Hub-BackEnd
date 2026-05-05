from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from app.config import Settings

from ..utils.logger import get_logger
from .content_asset_downloader import (
    ContentAsset,
    ContentAssetDownloadError,
    ContentAssetDownloader,
    DownloadedAsset,
    classify_attachment,
)
from .content_extractors.hwp_extractor import (
    ExtractedText,
    HwpTextExtractionError,
    HwpTextExtractor,
)
from .content_extractors.openai_provider import (
    GeneratedContent,
    OpenAIContentProvider,
    OpenAIProviderError,
)

logger = get_logger("crawler.services.content_enrichment")

FALLBACK_CONTENT_PREFIXES = (
    "[이미지 본문]",
    "[동영상 본문]",
    "[첨부파일 공지]",
)
FALLBACK_CONTENT_VALUES = {
    "",
    "본문 정보가 비어 있습니다.",
}


class ImageTextExtractor(Protocol):
    def extract_image_text(
        self,
        downloaded: DownloadedAsset,
        *,
        notice_meta: dict,
        min_text_length: int,
    ) -> ExtractedText:
        ...


class NoticeContentGenerator(Protocol):
    def generate_notice_content(
        self,
        *,
        notice_meta: dict,
        extracted_texts: list[ExtractedText],
    ) -> GeneratedContent:
        ...


@dataclass
class ContentEnrichmentRunResult:
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    calls_used: int = 0


class ContentEnrichmentService:
    def __init__(
        self,
        *,
        enabled: bool,
        min_text_length: int,
        max_assets_per_notice: int,
        max_calls_per_run: int,
        downloader: ContentAssetDownloader,
        hwp_extractor: HwpTextExtractor,
        image_extractor: ImageTextExtractor | None,
        content_generator: NoticeContentGenerator | None,
        provider_name: str,
        model_name: str,
    ) -> None:
        self.enabled = enabled
        self.min_text_length = min_text_length
        self.max_assets_per_notice = max_assets_per_notice
        self.max_calls_per_run = max_calls_per_run
        self.downloader = downloader
        self.hwp_extractor = hwp_extractor
        self.image_extractor = image_extractor
        self.content_generator = content_generator
        self.provider_name = provider_name
        self.model_name = model_name
        self.calls_used = 0

    @classmethod
    def from_settings(cls, settings: Settings) -> ContentEnrichmentService:
        downloader = ContentAssetDownloader(
            allowed_domains=settings.content_enrichment_allowed_domain_list,
            max_file_bytes=settings.content_enrichment_max_file_bytes,
        )
        hwp_extractor = HwpTextExtractor(
            min_text_length=settings.content_enrichment_min_text_length,
        )
        provider: OpenAIContentProvider | None = None
        if settings.openai_api_key:
            provider = OpenAIContentProvider(
                api_key=settings.openai_api_key,
                model=settings.content_enrichment_model,
                fallback_model=settings.content_enrichment_fallback_model,
                image_detail=settings.content_enrichment_image_detail,
            )

        return cls(
            enabled=settings.content_enrichment_enabled,
            min_text_length=settings.content_enrichment_min_text_length,
            max_assets_per_notice=settings.content_enrichment_max_assets_per_notice,
            max_calls_per_run=settings.content_enrichment_max_calls_per_run,
            downloader=downloader,
            hwp_extractor=hwp_extractor,
            image_extractor=provider,
            content_generator=provider,
            provider_name=settings.content_enrichment_provider,
            model_name=settings.content_enrichment_model,
        )

    def enrich_posts(self, posts: list[dict]) -> ContentEnrichmentRunResult:
        result = ContentEnrichmentRunResult()
        if not self.enabled:
            result.skipped = len(posts)
            return result

        if self.content_generator is None:
            logger.warning("content enrichment enabled but OPENAI_API_KEY is not configured")

        for post in posts:
            if not self.should_enrich(post):
                result.skipped += 1
                continue

            result.attempted += 1
            if self.content_generator is None:
                self._mark_failed(
                    post,
                    "missing_openai_api_key",
                    [],
                    trigger=detect_trigger(post),
                )
                result.failed += 1
                result.calls_used = self.calls_used
                continue

            if self._enrich_post(post):
                result.succeeded += 1
            else:
                result.failed += 1
            result.calls_used = self.calls_used

        return result

    def should_enrich(self, post: dict) -> bool:
        enrichment = post.get("content_enrichment")
        if isinstance(enrichment, dict) and enrichment.get("status") == "success":
            return False

        assets = self.find_supported_assets(post)
        if not assets:
            return False

        content = str(post.get("content") or "").strip()
        if is_fallback_content(content):
            return True

        return len("".join(content.split())) < self.min_text_length

    def find_supported_assets(self, post: dict) -> list[ContentAsset]:
        assets: list[ContentAsset] = []
        seen_urls: set[str] = set()

        for raw_asset in post.get("content_assets") or []:
            if not isinstance(raw_asset, dict):
                continue
            url = str(raw_asset.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            if raw_asset.get("type") != "inline_image":
                continue
            seen_urls.add(url)
            assets.append(
                ContentAsset(
                    type="inline_image",
                    name=str(raw_asset.get("name") or "inline-image"),
                    url=url,
                    source="body",
                )
            )

        for attachment in post.get("attachments") or []:
            if not isinstance(attachment, dict):
                continue
            url = str(attachment.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            name = str(attachment.get("name") or url)
            asset_type = classify_attachment(name, url)
            if asset_type is None:
                continue
            seen_urls.add(url)
            assets.append(
                ContentAsset(
                    type=asset_type,
                    name=name,
                    url=url,
                    source="attachment",
                )
            )

        return assets[: self.max_assets_per_notice]

    def _enrich_post(self, post: dict) -> bool:
        trigger = detect_trigger(post)
        assets = self.find_supported_assets(post)
        extracted_texts: list[ExtractedText] = []
        processed_assets: list[dict] = []
        errors: list[str] = []

        for asset in assets:
            try:
                downloaded = self.downloader.download(asset)
                extracted = self._extract_text(asset, downloaded, post)
                extracted_texts.append(extracted)
                processed_assets.append(
                    {
                        "type": asset.type,
                        "name": asset.name,
                        "url": asset.url,
                        "sha256": downloaded.sha256,
                        "method": extracted.method,
                    }
                )
            except (ContentAssetDownloadError, HwpTextExtractionError, OpenAIProviderError) as exc:
                code = getattr(exc, "code", exc.__class__.__name__)
                errors.append(str(code))
                logger.warning(
                    "content enrichment asset failed: title=%s asset=%s code=%s",
                    post.get("title"),
                    asset.url,
                    code,
                )
                continue

        if not extracted_texts:
            self._mark_failed(post, "no_extracted_text", errors, trigger=trigger)
            return False

        if self.content_generator is None:
            self._mark_failed(post, "missing_openai_api_key", errors, trigger=trigger)
            return False

        if not self._consume_call():
            self._mark_failed(post, "enrichment_call_budget_exceeded", errors, trigger=trigger)
            return False

        try:
            generated = self.content_generator.generate_notice_content(
                notice_meta=post,
                extracted_texts=extracted_texts,
            )
        except OpenAIProviderError as exc:
            self._mark_failed(post, exc.code, errors, trigger=trigger)
            return False

        if len("".join(generated.content.split())) < self.min_text_length:
            self._mark_failed(post, "generated_content_too_short", errors, trigger=trigger)
            return False

        original_content = str(post.get("content") or "")
        post.setdefault("content_original", original_content)
        post["content"] = generated.content
        if generated.summary:
            post["summary"] = generated.summary
        post["content_enrichment"] = {
            "enabled": True,
            "status": "success",
            "trigger": trigger,
            "provider": self.provider_name,
            "model": generated.model or self.model_name,
            "assets": processed_assets,
            "confidence": generated.confidence,
            "warnings": generated.warnings,
            "source_asset_names": generated.source_asset_names,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        return True

    def _extract_text(
        self,
        asset: ContentAsset,
        downloaded: DownloadedAsset,
        post: dict,
    ) -> ExtractedText:
        if asset.type == "hwp_attachment":
            return self.hwp_extractor.extract(downloaded)

        if self.image_extractor is None:
            raise OpenAIProviderError("missing_openai_api_key", "OPENAI_API_KEY is required")
        if not self._consume_call():
            raise OpenAIProviderError(
                "enrichment_call_budget_exceeded",
                "content enrichment call budget exceeded",
            )
        return self.image_extractor.extract_image_text(
            downloaded,
            notice_meta=post,
            min_text_length=self.min_text_length,
        )

    def _consume_call(self) -> bool:
        if self.calls_used >= self.max_calls_per_run:
            return False
        self.calls_used += 1
        return True

    def _mark_failed(
        self,
        post: dict,
        error_code: str,
        errors: list[str],
        *,
        trigger: str | None = None,
    ) -> None:
        post["content_enrichment"] = {
            "enabled": True,
            "status": "failed",
            "trigger": trigger or detect_trigger(post),
            "provider": self.provider_name,
            "error_code": error_code,
            "asset_errors": errors,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


def is_fallback_content(content: str) -> bool:
    stripped = (content or "").strip()
    if stripped in FALLBACK_CONTENT_VALUES:
        return True
    return any(stripped.startswith(prefix) for prefix in FALLBACK_CONTENT_PREFIXES)


def detect_trigger(post: dict) -> str:
    content = str(post.get("content") or "").strip()
    assets = post.get("content_assets") or []
    attachments = post.get("attachments") or []
    has_inline_image = any(
        isinstance(item, dict) and item.get("type") == "inline_image"
        for item in assets
    )
    attachment_types = {
        classify_attachment(str(item.get("name") or ""), str(item.get("url") or ""))
        for item in attachments
        if isinstance(item, dict)
    }
    has_hwp_attachment = "hwp_attachment" in attachment_types
    has_image_attachment = "image_attachment" in attachment_types

    if has_inline_image and has_hwp_attachment and has_image_attachment:
        return "inline_image_and_mixed_attachments"
    if has_inline_image and has_hwp_attachment:
        return "inline_image_and_hwp_attachment"
    if has_inline_image and has_image_attachment:
        return "inline_image_and_image_attachment"
    if has_hwp_attachment and has_image_attachment:
        return "mixed_attachments"
    if has_inline_image and content.startswith("[이미지 본문]"):
        return "image_only_body"
    if has_hwp_attachment:
        return "hwp_attachment_only"
    if has_image_attachment:
        return "image_attachment_only"
    if has_inline_image:
        return "inline_image"
    return "unknown"
