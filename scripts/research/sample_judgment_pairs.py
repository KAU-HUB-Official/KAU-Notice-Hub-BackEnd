"""판정 필요 쌍에서 실험용 표본을 뽑고, Claude 판정에 넘길 입력 묶음을 만든다.

- 모집단: classify_crosspost_pairs.py 결과 중 step이 "판정 필요"인 쌍(규칙으로 정하지 못한 쌍).
- 이미 판정한 쌍(--keep)은 그대로 표본에 넣고, 모자란 만큼 본문 유사도 구간 비율에 맞춰 새로 뽑는다.
- 판정 입력에는 본문만 넣는다(게시판·날짜·제목은 노이즈가 돼 제외한 2026-09-15 결정).

실행 (BackEnd 루트):
    .venv/bin/python -m scripts.research.sample_judgment_pairs \\
        --pairs data/research/crosspost_pairs_2026-09-15.json \\
        --posts data/research/kau_notices_clean_2026-09-15.json \\
        --keep data/research/analysis/labeling/claude_review_2026-09-15.json \\
        --size 200 --output data/research/judgment_sample_2026-09-16.json --batches <디렉터리> --batch-size 25
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SEED = 20260916
BODY_LIMIT = 6000
NEEDS_JUDGMENT = "판정 필요"


def similarity_bin(sim: float | None) -> str:
    if sim is None:
        return "비교 불가"
    return "<0.3" if sim < 0.3 else "0.3~0.6" if sim < 0.6 else "0.6~0.9"


def readable_body(content: str) -> str:
    c = re.sub(r"!\[[^\]]*\]\([^)]*\)", "[이미지]", content or "")
    c = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", c)
    c = re.sub(r"https?://\S+", "", c)
    c = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|~<> ])", r"\1", c)
    c = re.sub(r"(?m)\\\s*$", "", c)
    lines = [re.sub(r"^\s*#+\s*", "", line).replace("**", "").rstrip() for line in c.splitlines()]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return (text or "(본문 없음)")[:BODY_LIMIT]


def sample(universe: list[dict], kept_keys: set[tuple[str, str]], size: int) -> list[dict]:
    """kept_keys를 먼저 넣고, 남은 자리를 구간 비율에 맞춰 무작위로 채운다."""
    chosen = [p for p in universe if (p["a_url"], p["b_url"]) in kept_keys]
    rest = defaultdict(list)
    for p in universe:
        if (p["a_url"], p["b_url"]) not in kept_keys:
            rest[similarity_bin(p["body_similarity"])].append(p)
    need = size - len(chosen)
    if need <= 0:
        return chosen[:size]
    total = sum(len(v) for v in rest.values())
    rng = random.Random(SEED)
    quota = {b: round(need * len(v) / total) for b, v in rest.items()}
    for b, items in rest.items():
        rng.shuffle(items)
        chosen.extend(items[: quota[b]])
    leftovers = [p for b, items in rest.items() for p in items[quota[b] :]]
    rng.shuffle(leftovers)
    chosen.extend(leftovers[: max(0, size - len(chosen))])
    return chosen[:size]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pairs", type=Path, required=True, help="classify_crosspost_pairs.py 결과")
    parser.add_argument("--posts", type=Path, required=True, help="정리본 공지 JSON")
    parser.add_argument("--keep", type=Path, default=None, help="이미 판정한 쌍 목록(select_hard_pairs.py 결과)")
    parser.add_argument("--size", type=int, default=200)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batches", type=Path, default=None, help="판정 입력 묶음을 쓸 디렉터리")
    parser.add_argument("--batch-size", type=int, default=25)
    args = parser.parse_args(argv)

    posts = {p["original_url"]: p for p in json.loads(args.posts.read_text(encoding="utf-8"))}
    universe = [p for p in json.loads(args.pairs.read_text(encoding="utf-8"))["pairs"] if p["step"] == NEEDS_JUDGMENT]
    kept: dict[tuple[str, str], dict] = {}
    if args.keep:
        for r in json.loads(args.keep.read_text(encoding="utf-8"))["pairs"]:
            kept[(r["a_url"], r["b_url"])] = r
            kept[(r["b_url"], r["a_url"])] = r
    chosen = sample(universe, set(kept), args.size)
    chosen.sort(key=lambda p: (p["a_published_at"], p["a_url"]))

    rows: list[dict[str, Any]] = []
    for n, p in enumerate(chosen, 1):
        old = kept.get((p["a_url"], p["b_url"]))
        rows.append(
            {
                "no": str(n).zfill(3),
                "a_url": p["a_url"],
                "b_url": p["b_url"],
                "title_a": p["title_a"],
                "title_b": p["title_b"],
                "a_published_at": p["a_published_at"],
                "b_published_at": p["b_published_at"],
                "body_similarity": p["body_similarity"],
                "bin": similarity_bin(p["body_similarity"]),
                "source": "기존 판정" if old else "신규",
                "previous": (
                    {k: old[k] for k in ("claude_judgment", "claude_confidence", "claude_reason", "hard_reason")}
                    if old
                    else None
                ),
            }
        )
    summary = {
        "universe": len(universe),
        "size": len(rows),
        "by_source": dict(Counter(r["source"] for r in rows)),
        "by_bin": dict(sorted(Counter(r["bin"] for r in rows).items())),
        "universe_by_bin": dict(sorted(Counter(similarity_bin(p["body_similarity"]) for p in universe).items())),
    }
    args.output.write_text(
        json.dumps({"seed": SEED, "summary": summary, "pairs": rows}, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    if args.batches:
        todo = [r for r in rows if r["source"] == "신규"]
        args.batches.mkdir(parents=True, exist_ok=True)
        for i in range(0, len(todo), args.batch_size):
            chunk = todo[i : i + args.batch_size]
            items = [
                {
                    "no": r["no"],
                    "A": readable_body(posts[r["a_url"]].get("content") or ""),
                    "B": readable_body(posts[r["b_url"]].get("content") or ""),
                }
                for r in chunk
            ]
            path = args.batches / f"batch_{i // args.batch_size + 1}.json"
            path.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
            print("saved", path, len(items))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print("saved", args.output)


if __name__ == "__main__":
    main()
