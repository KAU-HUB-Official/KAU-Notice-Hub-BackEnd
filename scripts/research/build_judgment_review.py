"""표본 쌍의 Claude 판정을 모아 라벨을 정하고, 사람이 볼 쌍을 고른다.

- 표본: sample_judgment_pairs.py 결과(전부 규칙으로 정하지 못한 "판정 필요" 쌍).
- 라벨: Claude 판정을 라벨로 쓴다. 사람 검수는 아래 두 종류만 받는다(발표·논문에 밝힌다).
  - 어려움: Claude 확신이 낮은 쌍. 사람 판정으로 대체한다.
  - 대조: Claude가 확신한 쌍 중 무작위 몇 개. 확신한 구간의 라벨을 믿어도 되는지 확인한다.

실행 (BackEnd 루트):
    .venv/bin/python -m scripts.research.build_judgment_review \\
        --sample data/research/judgment_sample_2026-09-16.json \\
        --results <결과 디렉터리>/result_*.json --human-extra 10 \\
        --output data/research/judgment_review_2026-09-16.json
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path

SEED = 20260916
JUDGMENTS = ("merge", "keep_both")
CONFIDENCES = ("high", "low")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--results", nargs="*", type=Path, default=[], help="새로 판정한 결과 JSON들")
    parser.add_argument("--human-extra", type=int, default=10, help="사람에게 함께 보낼 대조용(확신) 쌍 수")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    sample = json.loads(args.sample.read_text(encoding="utf-8"))
    judged: dict[str, dict] = {}
    for path in args.results:
        for item in json.loads(path.read_text(encoding="utf-8")):
            if item.get("judgment") not in JUDGMENTS or item.get("confidence") not in CONFIDENCES:
                raise SystemExit(f"{path.name} 쌍 {item.get('no')}: judgment·confidence 값이 올바르지 않습니다.")
            if item["no"] in judged:
                raise SystemExit(f"쌍 {item['no']} 판정이 두 번 들어왔습니다: {path.name}")
            judged[item["no"]] = item

    pairs = []
    missing = []
    for row in sample["pairs"]:
        old = row.get("previous")
        new = judged.get(row["no"])
        if new:
            judgment, confidence, reason, hard_reason = (
                new["judgment"], new["confidence"], new.get("reason", ""), new.get("hard_reason", "")
            )
        elif old:
            judgment, confidence, reason, hard_reason = (
                old["claude_judgment"], old["claude_confidence"], old.get("claude_reason", ""), old.get("hard_reason", "")
            )
        else:
            missing.append(row["no"])
            continue
        pairs.append(
            {
                **{k: row[k] for k in ("no", "a_url", "b_url", "title_a", "title_b", "a_published_at", "b_published_at", "body_similarity", "bin", "source")},
                "claude_judgment": judgment,
                "claude_confidence": confidence,
                "claude_reason": reason,
                "hard_reason": hard_reason,
                "hard": confidence == "low",
            }
        )
    if missing:
        raise SystemExit(f"판정이 없는 쌍: {missing}")

    confident = [p for p in pairs if not p["hard"]]
    control = set(
        p["no"] for p in random.Random(SEED).sample(confident, min(args.human_extra, len(confident)))
    )
    for p in pairs:
        p["human_kind"] = "어려움" if p["hard"] else ("대조" if p["no"] in control else None)
        p["for_human"] = p["human_kind"] is not None

    summary = {
        "pairs": len(pairs),
        "by_source": dict(Counter(p["source"] for p in pairs)),
        "claude_judgment": dict(Counter(p["claude_judgment"] for p in pairs)),
        "hard": sum(p["hard"] for p in pairs),
        "hard_by_bin": dict(sorted(Counter(p["bin"] for p in pairs if p["hard"]).items())),
        "hard_rate_by_bin": {
            b: round(sum(p["hard"] for p in pairs if p["bin"] == b) / n, 2)
            for b, n in sorted(Counter(p["bin"] for p in pairs).items())
        },
        "for_human": dict(Counter(p["human_kind"] for p in pairs if p["for_human"])),
        "labels_from_claude": dict(Counter(p["claude_judgment"] for p in pairs if not p["for_human"])),
    }
    args.output.write_text(
        json.dumps(
            {
                "question": "두 공지를 하나로 묶어 본문 하나만 남겨도 읽는 대상자에게 지장이 없는가 (merge / keep_both)",
                "rule": "전부 규칙으로 정하지 못한 쌍. Claude 판정을 라벨로 쓰고, 확신 낮은 쌍과 대조용 확신 쌍만 사람이 본다.",
                "seed": SEED,
                "summary": summary,
                "pairs": pairs,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print("saved", args.output)


if __name__ == "__main__":
    main()
