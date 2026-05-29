from scripts.audit_markdown_quality import NoticeRecord, audit_record, should_fail


def _record(content: str) -> NoticeRecord:
    return NoticeRecord(
        id="notice-1",
        title="공지",
        source="source",
        url="https://example.com/notice/1",
        content=content,
    )


def test_audit_record_accepts_clean_markdown() -> None:
    issues = audit_record(
        _record(
            "## 제목\n\n"
            "본문입니다.\n\n"
            "- 항목 1\n"
            "- 항목 2\n\n"
            "| 구분 | 일정 |\n"
            "| --- | --- |\n"
            "| 신청 | 5/30 |"
        )
    )

    assert issues == []


def test_audit_record_flags_definitely_broken_markdown() -> None:
    issues = audit_record(
        _record(
            "<p>raw</p>\n"
            "| 구분 | 일정 |\n"
            "| --- |\n"
            "강조 **깨짐\n"
            "[링크](https://example.com"
        )
    )

    codes = {issue.code for issue in issues}
    assert "raw_html" in codes
    assert "table_column_mismatch" in codes
    assert "unbalanced_strong" in codes
    assert "unclosed_link_destination" in codes
    assert should_fail(issues, "P1")


def test_audit_record_flags_strict_suspicious_formatting() -> None:
    issues = audit_record(_record("자격 • 나이 • 경력\n\n    들여쓰기 코드처럼 보임"))

    codes = {issue.code for issue in issues}
    assert "inline_bullet" in codes
    assert "accidental_code_indent" in codes
    assert not should_fail(issues, "P1")
    assert should_fail(issues, "P2")
