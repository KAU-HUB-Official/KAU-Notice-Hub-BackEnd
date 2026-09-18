"""표본 쌍의 최종 라벨을 정한다: 팀원 라벨 + 최종 판정 + Claude 판정.

- 사람이 본 쌍(판정 어려움 + 대조): 팀원 답이 모두 같으면 그 답, 엇갈리면 최종 판정자의 답.
  최종 판정자가 "모르겠음"을 고른 쌍은 라벨 없이 남긴다(채점에서 뺀다).
- 사람이 보지 않은 쌍: Claude 판정을 라벨로 쓴다(확신 높음).

실행 (BackEnd 루트):
    .venv/bin/python -m scripts.research.finalize_judgment_labels \\
        --review data/research/judgment_review_2026-09-16.json \\
        --human data/research/analysis/labeling/human_labels.json \\
        --adjudication data/research/analysis/labeling/adjudication_박성진.json \\
        --output data/research/judgment_labels_2026-09-19.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

DECIDED = ("merge", "keep_both")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--review", type=Path, required=True, help="build_judgment_review.py 결과")
    parser.add_argument("--human", type=Path, required=True, help="collect_labels.py 결과(팀원 답)")
    parser.add_argument("--adjudication", type=Path, required=True, help="최종 판정 결과 파일(엇갈린 쌍)")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    review = json.loads(args.review.read_text(encoding="utf-8"))
    human = json.loads(args.human.read_text(encoding="utf-8"))
    adj = json.loads(args.adjudication.read_text(encoding="utf-8"))
    adjudicator = adj.get("labeler") or args.adjudication.stem
    adj_answers = {no: a for no, a in (adj.get("answers") or {}).items() if a.get("label")}

    by_urls = {frozenset((p["a_url"], p["b_url"])): p for p in human["pairs"]}
    rows = []
    for r in review["pairs"]:
        h = by_urls.get(frozenset((r["a_url"], r["b_url"])))
        row = {k: r[k] for k in ("no", "a_url", "b_url", "title_a", "title_b", "body_similarity", "bin", "claude_judgment", "claude_confidence")}
        if h is None:
            row.update(label=r["claude_judgment"], label_source="Claude", human_kind=None)
        else:
            labels = [a["label"] for a in h["answers"].values()]
            row.update(human_kind=r["human_kind"], page_no=h["no"], team_answers=dict(Counter(labels)))
            if len(set(labels)) == 1 and labels[0] in DECIDED:
                row.update(label=labels[0], label_source="팀원 만장일치")
            elif h["no"] in adj_answers:
                a = adj_answers[h["no"]]
                label = a["label"] if a["label"] in DECIDED else None
                row.update(label=label, label_source=f"최종 판정({adjudicator})", team_majority=h.get("majority"),
                           adjudication_memo=a.get("memo") or "")
            else:
                raise SystemExit(f"팀원 답이 엇갈렸는데 최종 판정이 없는 쌍: 페이지 {h['no']}")
        rows.append(row)

    labeled = [x for x in rows if x["label"]]
    human_rows = [x for x in labeled if x["label_source"] != "Claude"]
    adjudicated = [x for x in rows if x["label_source"].startswith("최종 판정")]
    summary = {
        "pairs": len(rows),
        "labeled": len(labeled),
        "unlabeled": [x["no"] for x in rows if not x["label"]],
        "by_source": dict(Counter(x["label_source"] for x in rows)),
        "label_counts": dict(Counter(x["label"] for x in labeled)),
        "claude_vs_final_on_human_pairs": {
            kind: {
                "pairs": sum(1 for x in human_rows if x["human_kind"] == kind),
                "agree": sum(1 for x in human_rows if x["human_kind"] == kind and x["label"] == x["claude_judgment"]),
            }
            for kind in ("어려움", "대조")
        },
        "adjudication": {
            "pairs": len(adjudicated),
            "same_as_team_majority": sum(1 for x in adjudicated if x.get("team_majority") and x["label"] == x["team_majority"]),
            "team_had_no_majority": sum(1 for x in adjudicated if not x.get("team_majority")),
            "same_as_claude": sum(1 for x in adjudicated if x["label"] == x["claude_judgment"]),
        },
    }
    args.output.write_text(
        json.dumps({"adjudicator": adjudicator, "summary": summary, "pairs": rows}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print("saved", args.output)


if __name__ == "__main__":
    main()
