from __future__ import annotations

import hashlib
import zipfile
from io import BytesIO

import pytest
import requests

from app.crawler.models.post import Post
from app.crawler.services.board_crawler import (
    _fill_missing_content_from_body_assets,
    _missing_required_fields,
    _required_field_failure_reason,
)
from app.crawler.services.content_asset_downloader import (
    ContentAsset,
    ContentAssetDownloadError,
    ContentAssetDownloader,
    DownloadedAsset,
    classify_attachment,
    extract_inline_embed_assets,
    extract_inline_image_assets,
    is_safe_asset_url,
)
from app.crawler.services.content_enrichment_service import (
    ContentEnrichmentService,
    detect_trigger,
    is_fallback_content,
    safe_asset_log_value,
    visible_text_length,
)
from app.crawler.services.content_extractors.hwp_extractor import (
    ExtractedText,
    HwpTextExtractor,
)
from app.crawler.services.content_extractors.openai_provider import (
    GeneratedContent,
    OpenAIContentProvider,
    OpenAIProviderError,
)


class FakeDownloader:
    def __init__(self, *, content_type: str = "image/png", data: bytes = b"image") -> None:
        self.content_type = content_type
        self.data = data
        self.calls = 0

    def download(self, asset: ContentAsset) -> DownloadedAsset:
        self.calls += 1
        return DownloadedAsset(
            asset=asset,
            data=self.data,
            content_type=self.content_type,
            sha256="fake-sha256",
        )


class FailingDownloader:
    def download(self, asset: ContentAsset) -> DownloadedAsset:
        raise ContentAssetDownloadError("asset_download_failed", "failed")


class FakeImageExtractor:
    def extract_image_text(
        self,
        downloaded: DownloadedAsset,
        *,
        notice_meta: dict,
        min_text_length: int,
    ) -> ExtractedText:
        return ExtractedText(
            text="2026학년도 장학금 신청 기간은 5월 10일부터 5월 20일까지입니다.",
            format="image",
            method="fake-image",
        )


class FakeContentGenerator:
    def generate_notice_content(
        self,
        *,
        notice_meta: dict,
        extracted_texts: list[ExtractedText],
    ) -> GeneratedContent:
        return GeneratedContent(
            content="2026학년도 장학금 신청 안내입니다. 신청 기간은 5월 10일부터 5월 20일까지입니다.",
            summary="장학금 신청 기간 안내",
            confidence="high",
            source_asset_names=["poster.png"],
            model="fake-model",
        )


class FakeOpenAIResponse:
    status_code = 200

    def json(self) -> dict:
        return {"output": [{"content": [{"type": "output_text", "text": "텍스트 추출 결과입니다."}]}]}


class FakeOpenAISession:
    def __init__(self) -> None:
        self.payload: dict | None = None

    def post(self, *args, **kwargs) -> FakeOpenAIResponse:
        self.payload = kwargs.get("json")
        return FakeOpenAIResponse()


class NoNetworkSession:
    def get(self, *args, **kwargs) -> object:
        raise AssertionError("data URL assets must not use HTTP download")


class TimeoutSession:
    def get(self, *args, **kwargs) -> object:
        raise requests.ReadTimeout("timed out")


class StreamingTimeoutResponse:
    status_code = 200
    url = "https://93.184.216.34/poster.png"
    headers = {"Content-Type": "image/png"}

    def iter_content(self, *args, **kwargs) -> object:
        raise requests.ReadTimeout("timed out")


class StreamingTimeoutSession:
    def get(self, *args, **kwargs) -> StreamingTimeoutResponse:
        return StreamingTimeoutResponse()


def make_service(
    *,
    downloader: object | None = None,
    image_extractor: object | None = None,
    content_generator: object | None = None,
    max_calls_per_run: int = 10,
) -> ContentEnrichmentService:
    return ContentEnrichmentService(
        enabled=True,
        min_text_length=30,
        max_assets_per_notice=3,
        max_calls_per_run=max_calls_per_run,
        downloader=downloader or FakeDownloader(),
        hwp_extractor=HwpTextExtractor(min_text_length=30),
        image_extractor=image_extractor or FakeImageExtractor(),
        content_generator=content_generator or FakeContentGenerator(),
        provider_name="fake",
        model_name="fake-model",
    )


def test_fallback_content_detection() -> None:
    # 기존 plain-text 형식 (마이그레이션 이전 JSON에 남아 있을 수 있음)
    assert is_fallback_content("[이미지 본문] 텍스트 본문 없음 (이미지 1개)")
    assert is_fallback_content("[동영상 본문] 텍스트 본문 없음 (동영상 1개)")
    assert is_fallback_content("[첨부파일 공지]\n- notice.hwp")
    # 신규 Markdown 형식
    assert is_fallback_content("**[이미지 본문]** 텍스트 본문 없음 (이미지 1개)")
    assert is_fallback_content("**[동영상 본문]** 텍스트 본문 없음 (동영상 1개)")
    assert is_fallback_content("**[첨부파일 공지]**\n\n- notice.hwp")
    assert is_fallback_content("본문 정보가 비어 있습니다.")
    assert not is_fallback_content("수강신청 기간 안내 본문입니다.")


def test_visible_text_length_ignores_image_link_markdown() -> None:
    # 포스터 공지: 본문이 이미지 링크 마크다운뿐 → 실제 텍스트 0
    poster = (
        "[![](http://college.kau.ac.kr/web/cmm/imageSrc.do?path=" + "a" * 200 + ")]"
        "(http://college.kau.ac.kr/web/cmm/imageSrc.do?path=" + "b" * 200 + ")"
    )
    assert len("".join(poster.split())) > 30  # 기존 길이 기준은 본문 있다고 오판
    assert visible_text_length(poster) == 0  # 실제 텍스트는 0

    # 이미지 + 실제 텍스트가 함께 있으면 텍스트 길이만 센다
    mixed = "![poster](http://x/y.png)\n\n수강신청 기간은 3월 2일부터 3월 6일까지입니다."
    assert visible_text_length(mixed) >= 20
    # 링크의 보이는 텍스트는 유지한다
    assert visible_text_length("[신청서 다운로드](http://x/y)") == len("신청서다운로드")


def test_should_enrich_targets_poster_only_notice() -> None:
    service = make_service()
    poster_post = {
        "title": "2026학년도 1학기 등록금 분할납부 안내",
        "content": "[![](http://college.kau.ac.kr/web/cmm/imageSrc.do?path=" + "a" * 200 + ")]"
        "(http://college.kau.ac.kr/web/cmm/imageSrc.do?path=" + "b" * 200 + ")",
        "content_assets": [
            {
                "type": "inline_image",
                "name": "poster.png",
                "url": "http://college.kau.ac.kr/web/cmm/imageSrc.do?path=" + "a" * 200,
                "source": "body",
            }
        ],
    }
    # 본문이 이미지 링크뿐이라 보강 대상으로 잡혀야 한다
    assert service.should_enrich(poster_post) is True

    # 실제 텍스트가 충분한 공지는 이미지가 있어도 보강하지 않는다
    text_post = {
        "title": "수강신청 안내",
        "content": "![poster](http://x/y.png)\n\n" + "수강신청 기간 안내 본문입니다. " * 3,
        "content_assets": poster_post["content_assets"],
    }
    assert service.should_enrich(text_post) is False


def test_extract_inline_image_assets_from_content_container() -> None:
    html = """
    <html>
      <body>
        <header><img src="/logo.png" /></header>
        <div class="view_conts">
          <img src="/files/poster.png" alt="장학금 포스터" />
        </div>
      </body>
    </html>
    """

    assets = extract_inline_image_assets(html, "https://kau.ac.kr/notice/read")

    assert assets == [
        {
            "type": "inline_image",
            "name": "장학금 포스터",
            "url": "https://kau.ac.kr/files/poster.png",
            "source": "body",
        }
    ]


def test_extract_inline_image_assets_cleans_escaped_src() -> None:
    html = """
    <div class="view_conts">
      <img src='\\"/web/cmm/imageSrc.do?path=notice/poster.jpg\\"' />
    </div>
    """

    assets = extract_inline_image_assets(
        html,
        "http://college.kau.ac.kr/web/pages/read.do?nttId=1",
    )

    assert (
        assets[0]["url"]
        == "http://college.kau.ac.kr/web/cmm/imageSrc.do?path=notice/poster.jpg"
    )


def test_extract_inline_image_assets_keeps_data_url_with_fallback_name() -> None:
    html = """
    <div class="view_conts">
      <img src="data:image/png;base64,aW1hZ2U=" />
    </div>
    """

    assets = extract_inline_image_assets(html, "https://kau.ac.kr/notice/read")

    assert assets == [
        {
            "type": "inline_image",
            "name": "inline-image-1",
            "url": "data:image/png;base64,aW1hZ2U=",
            "source": "body",
        }
    ]


def test_extract_inline_embed_assets_from_content_container() -> None:
    html = """
    <html>
      <body>
        <iframe src="https://example.com/header"></iframe>
        <div class="view_conts">
          <iframe src="https://www.youtube.com/embed/QIDKo72QBbE" title="안내 영상"></iframe>
        </div>
      </body>
    </html>
    """

    assets = extract_inline_embed_assets(html, "https://kau.ac.kr/notice/read")

    assert assets == [
        {
            "type": "inline_embed",
            "name": "안내 영상",
            "url": "https://www.youtube.com/embed/QIDKo72QBbE",
            "source": "body",
        }
    ]


def test_missing_content_uses_inline_image_fallback_before_required_check() -> None:
    post = Post(
        source_name="한국항공대학교",
        source_type="official",
        category_raw="일반공지",
        title="등록 안내",
        content="",
        published_at="2026-03-01",
        original_url="https://kau.ac.kr/notice/1",
        attachments=[],
        crawled_at="2026-05-05T00:00:00+00:00",
    )

    _fill_missing_content_from_body_assets(
        post,
        inline_images=[
            {
                "type": "inline_image",
                "name": "등록 안내 이미지",
                "url": "https://kau.ac.kr/poster.jpg",
                "source": "body",
            }
        ],
        inline_embeds=[],
    )

    assert post.content.startswith("**[이미지 본문]** 텍스트 본문 없음 (이미지 1개)")
    assert "등록 안내 이미지" in post.content


def test_missing_content_uses_inline_embed_fallback_before_required_check() -> None:
    post = Post(
        source_name="한국항공대학교",
        source_type="official",
        category_raw="일반공지",
        title="영상 안내",
        content="",
        published_at="2026-03-01",
        original_url="https://kau.ac.kr/notice/2",
        attachments=[],
        crawled_at="2026-05-05T00:00:00+00:00",
    )

    _fill_missing_content_from_body_assets(
        post,
        inline_images=[],
        inline_embeds=[
            {
                "type": "inline_embed",
                "name": "안내 영상",
                "url": "https://www.youtube.com/embed/QIDKo72QBbE",
                "source": "body",
            }
        ],
    )

    assert post.content.startswith("**[동영상 본문]** 텍스트 본문 없음 (동영상 1개)")
    assert "안내 영상" in post.content


def test_required_field_failure_reason_includes_missing_field_names() -> None:
    post = Post(
        source_name="한국항공대학교",
        source_type="official",
        category_raw="일반공지",
        title="",
        content="",
        published_at="2026-03-01",
        original_url="https://kau.ac.kr/notice/3",
        attachments=[],
        crawled_at="2026-05-05T00:00:00+00:00",
    )

    missing_fields = _missing_required_fields(post)

    assert missing_fields == ["title", "content"]
    assert _required_field_failure_reason(missing_fields) == (
        "required_field_empty:title,content"
    )


def test_detect_trigger_prefers_inline_image_and_hwp_attachment_mix() -> None:
    post = {
        "content": "[이미지 본문] 텍스트 본문 없음 (이미지 1개)",
        "content_assets": [
            {
                "type": "inline_image",
                "name": "poster.jpg",
                "url": "https://kau.ac.kr/poster.jpg",
                "source": "body",
            }
        ],
        "attachments": [
            {
                "name": "notice.hwp",
                "url": "https://kau.ac.kr/notice.hwp",
            }
        ],
    }

    assert detect_trigger(post) == "inline_image_and_hwp_attachment"


def test_detect_trigger_prefers_inline_image_and_mixed_attachments() -> None:
    post = {
        "content": "[이미지 본문] 텍스트 본문 없음 (이미지 1개)",
        "content_assets": [
            {
                "type": "inline_image",
                "name": "poster.jpg",
                "url": "https://kau.ac.kr/poster.jpg",
                "source": "body",
            }
        ],
        "attachments": [
            {
                "name": "notice.hwp",
                "url": "https://kau.ac.kr/notice.hwp",
            },
            {
                "name": "extra.png",
                "url": "https://kau.ac.kr/extra.png",
            },
        ],
    }

    assert detect_trigger(post) == "inline_image_and_mixed_attachments"


def test_detect_trigger_identifies_mixed_attachments_without_inline_image() -> None:
    post = {
        "content": "[첨부파일 공지]\n- notice.hwp\n- poster.png",
        "content_assets": [],
        "attachments": [
            {
                "name": "notice.hwp",
                "url": "https://kau.ac.kr/notice.hwp",
            },
            {
                "name": "poster.png",
                "url": "https://kau.ac.kr/poster.png",
            },
        ],
    }

    assert detect_trigger(post) == "mixed_attachments"


def test_classifies_supported_attachment_types() -> None:
    assert classify_attachment("poster.png", "https://kau.ac.kr/poster") == "image_attachment"
    assert classify_attachment("notice.hwp", "https://kau.ac.kr/download") == "hwp_attachment"
    assert classify_attachment("notice.pdf", "https://kau.ac.kr/notice.pdf") is None


def test_rejects_unsafe_asset_urls_without_network_lookup() -> None:
    assert not is_safe_asset_url("file:///tmp/poster.png", ["kau.ac.kr"])
    assert not is_safe_asset_url("http://localhost/poster.png", ["kau.ac.kr"])
    assert not is_safe_asset_url("http://127.0.0.1/poster.png", [])
    assert not is_safe_asset_url("https://evil.example/poster.png", ["kau.ac.kr"])


def test_empty_allowlist_permits_public_hosts_but_blocks_internal() -> None:
    # 도메인 화이트리스트를 끄면 공개 IP 호스트는 허용한다.
    assert is_safe_asset_url("http://93.184.216.34/poster.png", [])
    # localhost·사설/링크로컬 IP는 화이트리스트와 무관하게 계속 차단한다.
    assert not is_safe_asset_url("http://localhost/poster.png", [])
    assert not is_safe_asset_url("http://10.0.0.5/poster.png", [])
    assert not is_safe_asset_url("http://169.254.169.254/latest/meta-data/", [])
    assert not is_safe_asset_url("file:///etc/passwd", [])


def test_safe_asset_log_value_omits_data_url_payload() -> None:
    data_url = "data:image/png;base64," + ("a" * 500)

    assert safe_asset_log_value(data_url) == "data:image/png;base64,<omitted>"


def test_safe_asset_log_value_truncates_long_url() -> None:
    url = "https://kau.ac.kr/" + ("a" * 300)

    sanitized = safe_asset_log_value(url, max_length=40)

    assert sanitized == "https://kau.ac.kr/aaaaaaaaaaaaaaaaaaaaaa...<truncated:318 chars>"


def test_content_asset_downloader_decodes_inline_data_image() -> None:
    downloader = ContentAssetDownloader(
        allowed_domains=["kau.ac.kr"],
        max_file_bytes=10,
        session=NoNetworkSession(),
    )
    asset = ContentAsset(
        type="inline_image",
        name="poster.png",
        url="data:image/png;base64,aW1hZ2U=",
        source="body",
    )

    downloaded = downloader.download(asset)

    assert downloaded.data == b"image"
    assert downloaded.content_type == "image/png"
    assert downloaded.sha256 == hashlib.sha256(b"image").hexdigest()


def test_content_asset_downloader_rejects_large_data_image() -> None:
    downloader = ContentAssetDownloader(
        allowed_domains=["kau.ac.kr"],
        max_file_bytes=4,
        session=NoNetworkSession(),
    )
    asset = ContentAsset(
        type="inline_image",
        name="poster.png",
        url="data:image/png;base64,aW1hZ2U=",
        source="body",
    )

    with pytest.raises(ContentAssetDownloadError) as exc_info:
        downloader.download(asset)

    assert exc_info.value.code == "asset_too_large"


def test_content_asset_downloader_rejects_non_image_data_url() -> None:
    downloader = ContentAssetDownloader(
        allowed_domains=["kau.ac.kr"],
        max_file_bytes=10,
        session=NoNetworkSession(),
    )
    asset = ContentAsset(
        type="inline_image",
        name="poster.txt",
        url="data:text/plain;base64,aW1hZ2U=",
        source="body",
    )

    with pytest.raises(ContentAssetDownloadError) as exc_info:
        downloader.download(asset)

    assert exc_info.value.code == "unsupported_asset_type"


def test_content_asset_downloader_wraps_request_timeout() -> None:
    downloader = ContentAssetDownloader(
        allowed_domains=[],
        max_file_bytes=10,
        session=TimeoutSession(),
    )
    asset = ContentAsset(
        type="inline_image",
        name="poster.png",
        url="https://93.184.216.34/poster.png",
        source="body",
    )

    with pytest.raises(ContentAssetDownloadError) as exc_info:
        downloader.download(asset)

    assert exc_info.value.code == "asset_download_failed"


def test_content_asset_downloader_wraps_streaming_timeout() -> None:
    downloader = ContentAssetDownloader(
        allowed_domains=[],
        max_file_bytes=10,
        session=StreamingTimeoutSession(),
    )
    asset = ContentAsset(
        type="inline_image",
        name="poster.png",
        url="https://93.184.216.34/poster.png",
        source="body",
    )

    with pytest.raises(ContentAssetDownloadError) as exc_info:
        downloader.download(asset)

    assert exc_info.value.code == "asset_download_failed"


def test_hwp_extractor_reads_hwpx_zip_xml() -> None:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "Contents/section0.xml",
            "<root><p>장학금 신청 기간은 2026년 5월 10일부터 5월 20일까지입니다.</p></root>",
        )

    asset = ContentAsset(
        type="hwp_attachment",
        name="notice.hwpx",
        url="https://kau.ac.kr/notice.hwpx",
        source="attachment",
    )
    downloaded = DownloadedAsset(
        asset=asset,
        data=buffer.getvalue(),
        content_type="application/vnd.hancom.hwpx",
        sha256="fake",
    )

    extracted = HwpTextExtractor(min_text_length=10).extract(downloaded)

    assert extracted.format == "hwpx"
    assert extracted.method == "hwpx-xml"
    assert "장학금 신청 기간" in extracted.text


def test_content_enrichment_success_for_image_only_body() -> None:
    post = {
        "title": "장학금 신청 안내",
        "content": "[이미지 본문] 텍스트 본문 없음 (이미지 1개)",
        "published_at": "2026-05-01",
        "source_name": "한국항공대학교",
        "original_url": "https://kau.ac.kr/notice/1",
        "attachments": [],
        "content_assets": [
            {
                "type": "inline_image",
                "name": "poster.png",
                "url": "https://kau.ac.kr/poster.png",
                "source": "body",
            }
        ],
    }

    result = make_service().enrich_posts([post])

    assert result.attempted == 1
    assert result.succeeded == 1
    assert result.calls_used == 2
    assert post["content_original"].startswith("[이미지 본문]")
    assert "장학금 신청 안내" in post["content"]
    assert post["content_enrichment"]["status"] == "success"
    assert post["content_enrichment"]["trigger"] == "image_only_body"
    assert post["content_enrichment"]["assets"][0]["sha256"] == "fake-sha256"


def test_content_enrichment_skips_remaining_candidates_after_call_budget() -> None:
    first_post = {
        "title": "첫 번째 이미지 공지",
        "content": "[이미지 본문] 텍스트 본문 없음 (이미지 1개)",
        "content_assets": [
            {
                "type": "inline_image",
                "name": "first.png",
                "url": "https://kau.ac.kr/first.png",
                "source": "body",
            }
        ],
    }
    second_post = {
        "title": "두 번째 이미지 공지",
        "content": "[이미지 본문] 텍스트 본문 없음 (이미지 1개)",
        "content_assets": [
            {
                "type": "inline_image",
                "name": "second.png",
                "url": "https://kau.ac.kr/second.png",
                "source": "body",
            }
        ],
    }
    downloader = FakeDownloader()

    result = make_service(downloader=downloader, max_calls_per_run=2).enrich_posts(
        [first_post, second_post]
    )

    assert result.attempted == 1
    assert result.succeeded == 1
    assert result.failed == 0
    assert result.target_count == 2
    assert result.skipped == 1
    assert result.calls_used == 2
    assert downloader.calls == 1
    assert first_post["content_enrichment"]["status"] == "success"
    assert second_post["content_enrichment"]["status"] == "skipped"
    assert second_post["content_enrichment"]["reason"] == "enrichment_call_budget_exceeded"


def test_content_enrichment_marks_current_notice_skipped_when_budget_runs_out() -> None:
    post = {
        "title": "이미지 공지",
        "content": "[이미지 본문] 텍스트 본문 없음 (이미지 1개)",
        "content_assets": [
            {
                "type": "inline_image",
                "name": "poster.png",
                "url": "https://kau.ac.kr/poster.png",
                "source": "body",
            }
        ],
    }

    result = make_service(max_calls_per_run=1).enrich_posts([post])

    assert result.attempted == 0
    assert result.succeeded == 0
    assert result.failed == 0
    assert result.target_count == 1
    assert result.skipped == 1
    assert result.calls_used == 1
    assert post["content"] == "[이미지 본문] 텍스트 본문 없음 (이미지 1개)"
    assert "content_original" not in post
    assert post["content_enrichment"]["status"] == "skipped"
    assert post["content_enrichment"]["reason"] == "enrichment_call_budget_exceeded"


def test_content_enrichment_failure_keeps_fallback_content() -> None:
    post = {
        "title": "장학금 신청 안내",
        "content": "[첨부파일 공지]\n- poster.png",
        "attachments": [
            {
                "name": "poster.png",
                "url": "https://kau.ac.kr/poster.png",
            }
        ],
    }

    result = make_service(downloader=FailingDownloader()).enrich_posts([post])

    assert result.attempted == 1
    assert result.failed == 1
    assert post["content"] == "[첨부파일 공지]\n- poster.png"
    assert post["content_enrichment"]["status"] == "failed"
    assert post["content_enrichment"]["error_code"] == "no_extracted_text"
    assert post["content_enrichment"]["asset_errors"] == ["asset_download_failed"]


def test_content_enrichment_missing_key_fails_before_download() -> None:
    downloader = FakeDownloader()
    service = ContentEnrichmentService(
        enabled=True,
        min_text_length=30,
        max_assets_per_notice=3,
        max_calls_per_run=10,
        downloader=downloader,
        hwp_extractor=HwpTextExtractor(min_text_length=30),
        image_extractor=None,
        content_generator=None,
        provider_name="openai",
        model_name="gpt-4.1-mini",
    )
    post = {
        "title": "이미지 공지",
        "content": "[이미지 본문] 텍스트 본문 없음 (이미지 1개)",
        "content_assets": [
            {
                "type": "inline_image",
                "name": "poster.png",
                "url": "https://kau.ac.kr/poster.png",
                "source": "body",
            }
        ],
    }

    result = service.enrich_posts([post])

    assert result.failed == 1
    assert result.target_count == 1
    assert downloader.calls == 0
    assert post["content_enrichment"]["error_code"] == "missing_openai_api_key"


def test_content_enrichment_skips_normal_content() -> None:
    post = {
        "title": "정상 본문 공지",
        "content": (
            "이미 충분한 공지 본문이 있으므로 보강 대상이 아닙니다. "
            "신청 기간과 대상, 문의처가 본문에 포함되어 있습니다."
        ),
        "attachments": [{"name": "poster.png", "url": "https://kau.ac.kr/poster.png"}],
    }

    result = make_service().enrich_posts([post])

    assert result.target_count == 0
    assert result.skipped == 1
    assert "content_enrichment" not in post


def test_openai_provider_disables_response_storage() -> None:
    session = FakeOpenAISession()
    provider = OpenAIContentProvider(
        api_key="test-key",
        model="gpt-4.1-mini",
        session=session,  # type: ignore[arg-type]
    )
    asset = ContentAsset(
        type="image_attachment",
        name="poster.png",
        url="https://kau.ac.kr/poster.png",
        source="attachment",
    )
    downloaded = DownloadedAsset(
        asset=asset,
        data=b"image",
        content_type="image/png",
        sha256="fake",
    )

    provider.extract_image_text(
        downloaded,
        notice_meta={"title": "공지"},
        min_text_length=1,
    )

    assert session.payload is not None
    assert session.payload["store"] is False


def test_openai_provider_wraps_transport_timeout() -> None:
    class PostTimeoutSession:
        def post(self, *args, **kwargs) -> object:
            raise requests.ReadTimeout("read timed out")

    provider = OpenAIContentProvider(
        api_key="test-key",
        model="gpt-4.1-mini",
        session=PostTimeoutSession(),  # type: ignore[arg-type]
    )
    downloaded = DownloadedAsset(
        asset=ContentAsset(
            type="image_attachment",
            name="poster.png",
            url="https://kau.ac.kr/poster.png",
            source="attachment",
        ),
        data=b"image",
        content_type="image/png",
        sha256="fake",
    )
    # 전송 타임아웃이 raw requests 예외가 아니라 OpenAIProviderError로 감싸져야
    # enrich_posts가 한 공지만 실패 처리하고 계속 진행한다.
    with pytest.raises(OpenAIProviderError) as excinfo:
        provider.extract_image_text(
            downloaded,
            notice_meta={"title": "공지"},
            min_text_length=1,
        )
    assert excinfo.value.code == "openai_request_failed"
