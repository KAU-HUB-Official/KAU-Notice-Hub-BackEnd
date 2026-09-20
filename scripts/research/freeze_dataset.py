"""연구 데이터와 판정 결과를 고정한다: 파일 해시·건수·파이프라인 버전·커밋을 한 파일에 남긴다.

발표와 논문에 쓴 수치를 나중에 그대로 확인할 수 있게 하는 기록이다. 데이터 자체(data/)는 개인정보가 있어
저장소에 올리지 않으므로, 어떤 파일의 어떤 내용을 썼는지 해시로 남긴다.

실행 (BackEnd 루트):
    .venv/bin/python -m scripts.research.freeze_dataset --output data/research/frozen_2026-09-20.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

FILES = {
    "정리본 공지": "data/research/kau_notices_clean_2026-09-15.json",
    "교차 게시 쌍 분류": "data/research/crosspost_pairs_2026-09-15.json",
    "표본 라벨": "data/research/judgment_labels_2026-09-20.json",
    "표본 Claude 판정(0.9 미만)": "data/research/judgment_review_2026-09-16.json",
    "표본 Claude 판정(0.9 이상)": "data/research/judgment_review_high_2026-09-20.json",
    "팀원 라벨 집계": "data/research/analysis/labeling/human_labels.json",
    "LLM 평가 결과": "data/research/analysis/merge_llm_2026-09-20_full.json",
    "보강 캐시": "data/research/enrichment_cache.json",
    "본문 이미지 해시": "data/research/image_hash_cache.json",
    "수집 기록": "data/research/crawl_manifest_2026-09-15.json",
}


def digest(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    entry = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    try:
        loaded = json.loads(data)
    except json.JSONDecodeError:
        return entry
    if isinstance(loaded, list):
        entry["items"] = len(loaded)
    elif isinstance(loaded, dict):
        for key in ("pairs", "records", "posts"):
            if isinstance(loaded.get(key), list):
                entry["items"] = len(loaded[key])
                break
        if isinstance(loaded.get("summary"), dict):
            entry["summary"] = loaded["summary"]
    return entry


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    from scripts.research.judge_merge_llm import PIPELINE_VERSION

    files = {}
    for label, path in FILES.items():
        p = Path(path)
        files[label] = {"path": path, **digest(p)} if p.exists() else {"path": path, "없음": True}
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True).stdout.strip()
    record = {
        "frozen_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "pipeline_version": PIPELINE_VERSION,
        "git": {"commit": commit, "uncommitted_files": len(dirty.splitlines())},
        "files": files,
    }
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "summary"} for k, v in files.items()}, ensure_ascii=False, indent=1))
    print("pipeline", PIPELINE_VERSION, "| commit", commit[:8], "| 미커밋 파일", len(dirty.splitlines()))
    print("saved", args.output)


if __name__ == "__main__":
    main()
