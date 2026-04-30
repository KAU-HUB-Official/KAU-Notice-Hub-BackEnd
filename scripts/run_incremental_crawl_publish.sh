#!/usr/bin/env bash
set -euo pipefail

NOTICE_JSON_PATH="${NOTICE_JSON_PATH:-./data/kau_official_posts.json}"
CRAWLER_COMMAND="${CRAWLER_COMMAND:-python3 -m app.crawler.main --output \"\$CRAWLER_OUTPUT_PATH\"}"
MIN_RECORDS="${MIN_RECORDS:-1}"
MIN_RETAIN_RATIO="${MIN_RETAIN_RATIO:-0.5}"

final_path="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "$NOTICE_JSON_PATH")"
final_dir="$(dirname "$final_path")"
final_name="$(basename "$final_path")"
mkdir -p "$final_dir"

tmp_file="$(mktemp "$final_dir/.${final_name}.tmp.XXXXXX")"
cleanup() {
  if [[ -n "${tmp_file:-}" && -f "$tmp_file" ]]; then
    rm -f "$tmp_file"
  fi
}
trap cleanup EXIT

if [[ -f "$final_path" ]]; then
  cp "$final_path" "$tmp_file"
else
  printf '[]\n' > "$tmp_file"
fi

export CRAWLER_OUTPUT_PATH="$tmp_file"
bash -c "$CRAWLER_COMMAND"

python3 - "$tmp_file" "$final_path" "$MIN_RECORDS" "$MIN_RETAIN_RATIO" <<'PY'
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

next_path = Path(sys.argv[1])
final_path = Path(sys.argv[2])
min_records = int(sys.argv[3])
min_retain_ratio = float(sys.argv[4])
recent_notice_days = 365


def parse_published_date(value):
    if not value:
        return None

    match = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", str(value))
    if not match:
        return None

    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def has_permanent_notice_meta(item):
    source_meta = item.get("source_meta")
    if not isinstance(source_meta, list) or not source_meta:
        return bool(item.get("is_permanent_notice"))

    return any(
        isinstance(meta, dict) and bool(meta.get("is_permanent_notice"))
        for meta in source_meta
    )


def iter_published_values(item):
    yield item.get("published_at")
    yield item.get("date")
    yield item.get("created_at")
    yield item.get("updated_at")

    source_meta = item.get("source_meta")
    if isinstance(source_meta, list):
        for meta in source_meta:
            if isinstance(meta, dict):
                yield meta.get("published_at")
                yield meta.get("date")


def is_stale_general_notice(item):
    if not isinstance(item, dict) or has_permanent_notice_meta(item):
        return False

    published_dates = [
        parsed_date
        for value in iter_published_values(item)
        if (parsed_date := parse_published_date(value))
    ]
    if not published_dates:
        return False

    cutoff_date = date.today() - timedelta(days=recent_notice_days)
    return all(published_date <= cutoff_date for published_date in published_dates)


def count_retain_baseline_records(data):
    if not isinstance(data, list):
        return 0
    return sum(
        1
        for item in data
        if isinstance(item, dict) and not is_stale_general_notice(item)
    )

try:
    next_data = json.loads(next_path.read_text(encoding="utf-8"))
except Exception as exc:
    raise SystemExit(f"Invalid crawler output JSON: {exc}")

if not isinstance(next_data, list):
    raise SystemExit("Invalid crawler output JSON: root must be an array.")

next_count = len(next_data)
if next_count < min_records:
    raise SystemExit(f"Refusing publish: record count {next_count} < MIN_RECORDS {min_records}.")

old_count = 0
if final_path.exists():
    try:
        old_data = json.loads(final_path.read_text(encoding="utf-8"))
        if isinstance(old_data, list):
            old_count = count_retain_baseline_records(old_data)
    except Exception:
        old_count = 0

if old_count > 0 and next_count < old_count * min_retain_ratio:
    raise SystemExit(
        "Refusing publish: record count dropped from retain baseline "
        f"{old_count} to {next_count}, below MIN_RETAIN_RATIO {min_retain_ratio}."
    )

print(f"Validated {next_count} notices for publish.")
PY

mv -f "$tmp_file" "$final_path"
tmp_file=""
echo "Published notice JSON: $final_path"
