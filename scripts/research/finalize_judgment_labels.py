"""표본 쌍의 최종 라벨을 정한다: 팀원 라벨 + 최종 판정 + Claude 판정.

- 사람이 본 쌍(판정 어려움 + 대조): 팀원 답이 모두 같으면 그 답, 엇갈리면 최종 판정자의 답.
- 사람이 보지 않은 쌍: Claude 판정을 라벨로 쓴다.
- 애매하면 keep_both (2026-09-20 결정): 최종 판정자가 "모르겠음"을 고른 쌍, 팀원이 보지 않았는데 Claude 확신이
  낮은 쌍은 keep_both 로 둔다. 둘 다 남기는 것도 정답이므로 판정을 비워 두지 않는다.
- --human, --adjudication 은 없어도 된다. 없으면 모든 쌍을 Claude 판정과 위 규칙으로 정한다.

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
    parser.add_argument("--review", nargs="+", type=Path, required=True, help="build_judgment_review.py 결과(여러 개 가능)")
    parser.add_argument("--human", type=Path, default=None, help="collect_labels.py 결과(팀원 답)")
    parser.add_argument("--adjudication", type=Path, default=None, help="최종 판정 결과 파일(엇갈린 쌍)")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    review_pairs = []
    for n, path in enumerate(args.review, 1):
        for pair in json.loads(path.read_text(encoding="utf-8"))["pairs"]:
            # 표본 파일이 여러 개면 쌍 번호가 겹치므로 파일 순서를 앞에 붙여 구분한다.
            review_pairs.append({**pair, "no": f"{n}-{pair['no']}" if len(args.review) > 1 else pair["no"],
                                 "sample": path.stem})
    human = json.loads(args.human.read_text(encoding="utf-8")) if args.human else {"pairs": []}
    adj = json.loads(args.adjudication.read_text(encoding="utf-8")) if args.adjudication else {}
    adjudicator = adj.get("labeler") or (args.adjudication.stem if args.adjudication else None)
    adj_answers = {no: a for no, a in (adj.get("answers") or {}).items() if a.get("label")}

    by_urls = {frozenset((p["a_url"], p["b_url"])): p for p in human["pairs"]}
    rows = []
    for r in review_pairs:
        h = by_urls.get(frozenset((r["a_url"], r["b_url"])))
        row = {k: r[k] for k in ("no", "sample", "a_url", "b_url", "title_a", "title_b", "body_similarity", "bin", "claude_judgment", "claude_confidence")}
        if h is None:
            ambiguous = r["claude_confidence"] == "low"
            row.update(
                label="keep_both" if ambiguous else r["claude_judgment"],
                label_source="애매하여 keep_both" if ambiguous else "Claude",
                human_kind=None,
            )
        else:
            labels = [a["label"] for a in h["answers"].values()]
            row.update(human_kind=r["human_kind"], page_no=h["no"], team_answers=dict(Counter(labels)))
            if len(set(labels)) == 1 and labels[0] in DECIDED:
                row.update(label=labels[0], label_source="팀원 만장일치")
            elif h["no"] in adj_answers:
                a = adj_answers[h["no"]]
                ambiguous = a["label"] not in DECIDED
                row.update(
                    label="keep_both" if ambiguous else a["label"],
                    label_source="애매하여 keep_both" if ambiguous else f"최종 판정({adjudicator})",
                    team_majority=h.get("majority"),
                    adjudication_memo=a.get("memo") or "",
                )
            else:
                raise SystemExit(f"팀원 답이 엇갈렸는데 최종 판정이 없는 쌍: 페이지 {h['no']}")
        rows.append(row)

    labeled = [x for x in rows if x["label"]]
    human_rows = [x for x in labeled if x["human_kind"]]
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
        "ambiguous_to_keep_both": sum(1 for x in rows if x["label_source"] == "애매하여 keep_both"),
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
