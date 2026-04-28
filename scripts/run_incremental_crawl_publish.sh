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
import sys
from pathlib import Path

next_path = Path(sys.argv[1])
final_path = Path(sys.argv[2])
min_records = int(sys.argv[3])
min_retain_ratio = float(sys.argv[4])

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
            old_count = len(old_data)
    except Exception:
        old_count = 0

if old_count > 0 and next_count < old_count * min_retain_ratio:
    raise SystemExit(
        "Refusing publish: record count dropped from "
        f"{old_count} to {next_count}, below MIN_RETAIN_RATIO {min_retain_ratio}."
    )

print(f"Validated {next_count} notices for publish.")
PY

mv -f "$tmp_file" "$final_path"
tmp_file=""
echo "Published notice JSON: $final_path"
