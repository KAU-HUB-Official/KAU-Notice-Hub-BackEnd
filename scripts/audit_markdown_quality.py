from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


SEVERITY_RANK = {"P0": 0, "P1": 1, "P2": 2}

DANGEROUS_HTML_TAG_RE = re.compile(
    r"</?(?:script|style|iframe|object|embed|form|input|textarea|button)\b",
    flags=re.IGNORECASE,
)
RAW_HTML_TAG_RE = re.compile(
    r"</?(?:p|div|section|article|table|thead|tbody|tr|td|th|ul|ol|li|h[1-6]|img|a|br|span|strong|em|b|i)\b",
    flags=re.IGNORECASE,
)
HTML_ENTITY_RE = re.compile(
    r"&(?:nbsp|amp|lt|gt|quot|apos|#[0-9]+|#x[0-9a-f]+);",
    flags=re.IGNORECASE,
)
DATA_URI_RE = re.compile(r"\bdata:(?:image|application)/", flags=re.IGNORECASE)
UNSAFE_LINK_RE = re.compile(
    r"(?<!\\)!?(?<!\\)\[[^\]\n]*\]\(\s*(?:javascript|data):",
    flags=re.IGNORECASE,
)
EMPTY_LINK_RE = re.compile(r"(?<!\\)!?(?<!\\)\[[^\]\n]*\]\(\s*\)")
LINK_WITH_SPACE_DEST_RE = re.compile(
    r"(?<!\\)!?(?<!\\)\[[^\]\n]*\]\((?!<)[^\s)\n]+[ \t]+(?![\"'][^)\n]*\))[^)\n]*\)"
)
UNCLOSED_LINK_DEST_RE = re.compile(r"(?<!\\)!?(?<!\\)\[[^\]\n]*\]\([^)\n]*$")
UNCLOSED_LINK_TEXT_RE = re.compile(r"(?<!\\)!?(?<!\\)\[[^\]\n]*$")
INLINE_SAFE_BULLET_RE = re.compile(r"(?<=\S)[ \t]+(?=[•▪○]\s*\S)")
INLINE_DASH_LABEL_RE = re.compile(
    r"(?<=[^\s\-\d])(?=-[ \t]+[가-힣A-Za-z][가-힣A-Za-z\d]{0,14}[ \t:])"
)
INLINE_NUMBER_MARKER_RE = re.compile(r"(?<=[가-힣\)\]\d])(?=\d+\)\s+\S)")
INLINE_HANGUL_MARKER_RE = re.compile(r"(?<=[\.\)\]\d])(?=[가-사]\.\s+[가-힣A-Za-z])")
ACCIDENTAL_CODE_INDENT_RE = re.compile(r"^[ \t]{4,}\S")
TABLE_SEPARATOR_CELL_RE = re.compile(r":?-{3,}:?")


@dataclass(frozen=True)
class NoticeRecord:
    id: str
    title: str
    source: str
    url: str
    content: str


@dataclass(frozen=True)
class MarkdownIssue:
    notice_id: str
    title: str
    source: str
    url: str
    severity: str
    code: str
    message: str
    line: int | None = None
    excerpt: str = ""


def audit_record(record: NoticeRecord) -> list[MarkdownIssue]:
    issues: list[MarkdownIssue] = []
    seen_codes: set[str] = set()

    def add(
        severity: str,
        code: str,
        message: str,
        *,
        line: int | None = None,
        excerpt: str = "",
    ) -> None:
        if code in seen_codes:
            return
        seen_codes.add(code)
        issues.append(
            MarkdownIssue(
                notice_id=record.id,
                title=record.title,
                source=record.source,
                url=record.url,
                severity=severity,
                code=code,
                message=message,
                line=line,
                excerpt=_trim_excerpt(excerpt),
            )
        )

    content = record.content or ""
    if not content.strip():
        add("P0", "empty_content", "content is empty")
        return issues

    if DANGEROUS_HTML_TAG_RE.search(content):
        line, excerpt = _first_matching_line(content, DANGEROUS_HTML_TAG_RE)
        add("P0", "dangerous_raw_html", "dangerous raw HTML tag remains", line=line, excerpt=excerpt)

    if DATA_URI_RE.search(content):
        line, excerpt = _first_matching_line(content, DATA_URI_RE)
        add("P0", "data_uri", "data URI remains in Markdown content", line=line, excerpt=excerpt)

    if UNSAFE_LINK_RE.search(content):
        line, excerpt = _first_matching_line(content, UNSAFE_LINK_RE)
        add("P0", "unsafe_link", "javascript/data link destination remains", line=line, excerpt=excerpt)

    if RAW_HTML_TAG_RE.search(content):
        line, excerpt = _first_matching_line(content, RAW_HTML_TAG_RE)
        add("P1", "raw_html", "raw HTML tag remains", line=line, excerpt=excerpt)

    if "<!--" in content or "-->" in content:
        line, excerpt = _first_line_with(content, "<!--")
        add("P1", "html_comment", "HTML comment marker remains", line=line, excerpt=excerpt)

    if _has_unbalanced_fences(content, "```") or _has_unbalanced_fences(content, "~~~"):
        line, excerpt = _first_fence_line(content)
        add("P0", "unclosed_fence", "fenced code block marker is not balanced", line=line, excerpt=excerpt)

    if EMPTY_LINK_RE.search(content):
        line, excerpt = _first_matching_line(content, EMPTY_LINK_RE)
        add("P1", "empty_link_destination", "Markdown link/image has an empty destination", line=line, excerpt=excerpt)

    _audit_lines(content, add)
    _audit_tables(content, add)

    return sorted(issues, key=lambda issue: (SEVERITY_RANK[issue.severity], issue.code))


def load_json_records(path: Path) -> list[NoticeRecord]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit(f"{path} must contain a JSON array.")

    records: list[NoticeRecord] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        records.append(
            NoticeRecord(
                id=_string_value(item.get("id")) or _string_value(item.get("original_url")) or str(index),
                title=_string_value(item.get("title")) or f"untitled {index}",
                source=_source_label(item.get("source_name") or item.get("source")),
                url=_string_value(item.get("original_url") or item.get("url")),
                content=_string_value(item.get("content")),
            )
        )
    return records


def load_db_records(path: Path) -> list[NoticeRecord]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, title, content, url, source_group
            FROM notices
            ORDER BY published_at DESC, id
            """
        ).fetchall()
    finally:
        conn.close()

    return [
        NoticeRecord(
            id=_string_value(row["id"]),
            title=_string_value(row["title"]),
            source=_string_value(row["source_group"]),
            url=_string_value(row["url"]),
            content=_string_value(row["content"]),
        )
        for row in rows
    ]


def audit_records(records: Iterable[NoticeRecord]) -> list[MarkdownIssue]:
    issues: list[MarkdownIssue] = []
    for record in records:
        issues.extend(audit_record(record))
    return issues


def should_fail(issues: Iterable[MarkdownIssue], fail_on: str) -> bool:
    threshold = SEVERITY_RANK[fail_on]
    return any(SEVERITY_RANK[issue.severity] <= threshold for issue in issues)


def _audit_lines(content: str, add: Any) -> None:
    in_fence = False
    for line_number, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        line_without_code = _strip_inline_code(line)

        if _count_unescaped_backticks(line_without_code) % 2 == 1:
            add(
                "P1",
                "unbalanced_inline_code",
                "inline code marker is not balanced on a line",
                line=line_number,
                excerpt=line,
            )

        if UNCLOSED_LINK_DEST_RE.search(line_without_code):
            add(
                "P1",
                "unclosed_link_destination",
                "Markdown link/image destination is not closed",
                line=line_number,
                excerpt=line,
            )

        if "[^" not in line_without_code and UNCLOSED_LINK_TEXT_RE.search(line_without_code):
            add(
                "P1",
                "unclosed_link_text",
                "Markdown link/image text is not closed",
                line=line_number,
                excerpt=line,
            )

        if LINK_WITH_SPACE_DEST_RE.search(line_without_code):
            add(
                "P2",
                "link_destination_space",
                "Markdown link/image destination contains unescaped whitespace",
                line=line_number,
                excerpt=line,
            )

        if HTML_ENTITY_RE.search(line_without_code):
            add(
                "P2",
                "html_entity",
                "HTML entity remains in rendered Markdown text",
                line=line_number,
                excerpt=line,
            )

        if _looks_like_accidental_indented_code(content, line_number, line):
            add(
                "P2",
                "accidental_code_indent",
                "line may render as an unintended indented code block",
                line=line_number,
                excerpt=line,
            )

        if INLINE_SAFE_BULLET_RE.search(line_without_code):
            add(
                "P2",
                "inline_bullet",
                "bullet marker appears inline instead of starting a new line",
                line=line_number,
                excerpt=line,
            )

        if INLINE_DASH_LABEL_RE.search(line_without_code):
            add(
                "P2",
                "inline_dash_label",
                "dash label appears inline instead of starting a new line",
                line=line_number,
                excerpt=line,
            )

        if INLINE_NUMBER_MARKER_RE.search(line_without_code) or INLINE_HANGUL_MARKER_RE.search(line_without_code):
            add(
                "P2",
                "inline_ordered_marker",
                "ordered marker appears inline instead of starting a new line",
                line=line_number,
                excerpt=line,
            )

    if re.search(r"\n{3,}", content):
        line, excerpt = _first_repeated_blank_line(content)
        add("P2", "repeated_blank_lines", "three or more blank lines remain", line=line, excerpt=excerpt)

    content_without_code = "\n".join(_strip_inline_code(line) for line in content.splitlines())
    if content_without_code.count("**") % 2 == 1:
        line, excerpt = _first_line_with(content, "**")
        add(
            "P1",
            "unbalanced_strong",
            "strong emphasis marker is not balanced",
            line=line,
            excerpt=excerpt,
        )


def _audit_tables(content: str, add: Any) -> None:
    lines = content.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not _is_table_row(line):
            if _is_table_separator_row(line):
                add(
                    "P1",
                    "orphan_table_separator",
                    "table separator row appears without a table header",
                    line=index + 1,
                    excerpt=line,
                )
            index += 1
            continue

        if index + 1 >= len(lines) or not _is_table_separator_row(lines[index + 1]):
            add(
                "P2",
                "table_row_without_separator",
                "pipe-delimited row is not followed by a Markdown table separator",
                line=index + 1,
                excerpt=line,
            )
            index += 1
            continue

        header_cells = _table_cells(line)
        separator_cells = _table_cells(lines[index + 1])
        if all(not cell for cell in header_cells):
            add(
                "P1",
                "empty_table_header",
                "Markdown table has an empty header row",
                line=index + 1,
                excerpt=line,
            )
        if len(header_cells) != len(separator_cells):
            add(
                "P1",
                "table_column_mismatch",
                "table header and separator column counts differ",
                line=index + 2,
                excerpt=lines[index + 1],
            )

        expected_columns = len(header_cells)
        index += 2
        while index < len(lines) and _is_table_row(lines[index]):
            row_cells = _table_cells(lines[index])
            if len(row_cells) != expected_columns:
                add(
                    "P1",
                    "table_column_mismatch",
                    "table row column count differs from header",
                    line=index + 1,
                    excerpt=lines[index],
                )
            index += 1


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _source_label(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(_string_value(item) for item in value if _string_value(item))
    return _string_value(value)


def _trim_excerpt(value: str, *, limit: int = 180) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _first_matching_line(content: str, pattern: re.Pattern[str]) -> tuple[int | None, str]:
    for line_number, line in enumerate(content.splitlines(), start=1):
        if pattern.search(line):
            return line_number, line
    return None, ""


def _first_line_with(content: str, needle: str) -> tuple[int | None, str]:
    for line_number, line in enumerate(content.splitlines(), start=1):
        if needle in line:
            return line_number, line
    return None, ""


def _first_fence_line(content: str) -> tuple[int | None, str]:
    for line_number, line in enumerate(content.splitlines(), start=1):
        if line.strip().startswith(("```", "~~~")):
            return line_number, line
    return None, ""


def _has_unbalanced_fences(content: str, fence: str) -> bool:
    return sum(1 for line in content.splitlines() if line.strip().startswith(fence)) % 2 == 1


def _strip_inline_code(line: str) -> str:
    return re.sub(r"`[^`\n]*`", "", line)


def _count_unescaped_backticks(line: str) -> int:
    count = 0
    escaped = False
    for char in line:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "`":
            count += 1
    return count


def _looks_like_accidental_indented_code(content: str, line_number: int, line: str) -> bool:
    if not ACCIDENTAL_CODE_INDENT_RE.search(line):
        return False
    lines = content.splitlines()
    previous = "" if line_number <= 1 else lines[line_number - 2]
    return not previous.strip()


def _first_repeated_blank_line(content: str) -> tuple[int | None, str]:
    blank_count = 0
    for line_number, line in enumerate(content.splitlines(), start=1):
        if line.strip():
            blank_count = 0
            continue
        blank_count += 1
        if blank_count >= 3:
            return line_number, ""
    return None, ""


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_table_separator_row(line: str) -> bool:
    if not _is_table_row(line):
        return False
    cells = _table_cells(line)
    return bool(cells) and all(TABLE_SEPARATOR_CELL_RE.fullmatch(cell) for cell in cells)


def print_text_report(
    *,
    source_label: str,
    total: int,
    issues: list[MarkdownIssue],
    fail_on: str,
    examples_per_code: int,
) -> None:
    failing = [issue for issue in issues if SEVERITY_RANK[issue.severity] <= SEVERITY_RANK[fail_on]]
    print(f"Markdown audit: source={source_label} total={total} issues={len(issues)} failing={len(failing)}")
    if not issues:
        print("OK: no Markdown quality issues found.")
        return

    print("\nIssue summary:")
    summary = Counter((issue.severity, issue.code) for issue in issues)
    for (severity, code), count in sorted(summary.items(), key=lambda item: (SEVERITY_RANK[item[0][0]], item[0][1])):
        print(f"- {severity} {code}: {count}")

    print("\nExamples:")
    grouped: dict[tuple[str, str], list[MarkdownIssue]] = defaultdict(list)
    for issue in issues:
        grouped[(issue.severity, issue.code)].append(issue)

    for key in sorted(grouped, key=lambda item: (SEVERITY_RANK[item[0]], item[1])):
        severity, code = key
        for issue in grouped[key][:examples_per_code]:
            location = f":{issue.line}" if issue.line else ""
            print(f"- [{severity} {code}] id={issue.notice_id}{location}")
            print(f"  title={issue.title}")
            if issue.source:
                print(f"  source={issue.source}")
            if issue.url:
                print(f"  url={issue.url}")
            if issue.excerpt:
                print(f"  excerpt={issue.excerpt}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit notice Markdown quality.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--json", type=Path, default=Path("data/kau_official_posts.json"))
    source.add_argument("--db", type=Path)
    parser.add_argument(
        "--fail-on",
        choices=["P0", "P1", "P2"],
        default="P1",
        help="Exit with 1 when issues at this severity or higher exist. P2 is strictest.",
    )
    parser.add_argument("--examples-per-code", type=int, default=3)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.db:
        source_label = str(args.db)
        records = load_db_records(args.db)
    else:
        source_label = str(args.json)
        records = load_json_records(args.json)

    issues = audit_records(records)
    if args.format == "json":
        print(
            json.dumps(
                {
                    "source": source_label,
                    "total": len(records),
                    "issues": [asdict(issue) for issue in issues],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print_text_report(
            source_label=source_label,
            total=len(records),
            issues=issues,
            fail_on=args.fail_on,
            examples_per_code=args.examples_per_code,
        )
    return 1 if should_fail(issues, args.fail_on) else 0


if __name__ == "__main__":
    sys.exit(main())
