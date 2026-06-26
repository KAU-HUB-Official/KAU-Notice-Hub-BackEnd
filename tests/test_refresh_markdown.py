"""scripts/refresh_markdown_content.py 의 content 소유권 규칙 테스트.

refresh는 원문(content_original)을 항상 갱신하되, enrichment가 채운 읽는 본문
(content)은 보존해야 한다 — 보강 본문을 원본 이미지로 덮어 enrichment와 desync되던
버그(content_enrichment.status=success인데 content는 이미지) 방지.
"""

from __future__ import annotations

from scripts.refresh_markdown_content import apply_refreshed_content


def test_enriched_post_preserves_content_updates_original() -> None:
    post = {
        "content": "도서관 마일리지 프로그램 신청 안내 (AI 재구성 본문)...",
        "content_enrichment": {"status": "success"},
    }
    preserved = apply_refreshed_content(post, "![배너](http://x/y.png)")
    assert preserved is True
    # 보강 본문 보존
    assert post["content"] == "도서관 마일리지 프로그램 신청 안내 (AI 재구성 본문)..."
    # 원문만 갱신
    assert post["content_original"] == "![배너](http://x/y.png)"


def test_non_enriched_post_updates_content_and_original() -> None:
    post = {"content": "오래된 마크다운 본문"}
    preserved = apply_refreshed_content(post, "새 마크다운 본문")
    assert preserved is False
    assert post["content"] == "새 마크다운 본문"
    assert post["content_original"] == "새 마크다운 본문"


def test_failed_enrichment_is_not_preserved() -> None:
    # status가 success가 아니면(failed/skipped) 보강 본문이 아니므로 content를 갱신한다
    post = {"content": "이미지뿐", "content_enrichment": {"status": "failed"}}
    preserved = apply_refreshed_content(post, "재파싱한 새 본문")
    assert preserved is False
    assert post["content"] == "재파싱한 새 본문"
    assert post["content_original"] == "재파싱한 새 본문"
