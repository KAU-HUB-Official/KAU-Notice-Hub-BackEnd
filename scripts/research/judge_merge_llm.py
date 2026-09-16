"""표본 쌍을 LLM에게 판정시킨다: 두 공지를 하나로 묶어도 되는가.

- 입력은 본문만 넘긴다. 게시판·게시일·제목·첨부 이름은 대상 판단을 흔드는 노이즈라 뺐다(2026-09-15 결정).
- 라벨과 비교해 일치율을 낸다. 라벨은 Claude 판정이며, 사람이 라벨링한 쌍(human_labels)이 있으면 그것을 우선한다.
- OpenAI 비용이 든다. --limit 으로 호출할 쌍 수를 반드시 정한다.

실행 (BackEnd 루트):
    .venv/bin/python -m scripts.research.judge_merge_llm \\
        --review data/research/judgment_review_2026-09-16.json \\
        --posts data/research/kau_notices_clean_2026-09-15.json \\
        --limit 200 --output data/research/analysis/merge_llm_2026-09-16.json
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests

from app.config import get_settings

BODY_CHARS = 6000
JUDGMENTS = ("merge", "keep_both")

INSTRUCTIONS = """두 대학 공지의 본문 A, B를 읽고, 둘을 하나로 묶어 본문 하나만 남겨도 읽는 대상자에게 지장이 없는지 정한다.

- judgment: "merge" 또는 "keep_both".
  - merge: 한쪽 본문만 남겨도 되거나, 대상마다 다른 부분(연락처·제출처·마감일 등)을 한 공지에 함께 적으면 되는 경우.
  - keep_both: 합치면 헷갈리거나 정보가 빠지는 경우. 서로 다른 집단(학부와 대학원, 다른 학과, 다른 과정)에
    각각 다른 일정·조건이 적용되면 keep_both다.
- reason: 판단 근거 한 문장. 본문에 적힌 내용만 근거로 삼고 없는 사실을 추측하지 않는다."""

SCHEMA = {
    "type": "json_schema",
    "name": "merge_judgment",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["judgment", "reason"],
        "properties": {
            "judgment": {"type": "string", "enum": list(JUDGMENTS)},
            "reason": {"type": "string"},
        },
    },
}


def body_text(post: dict) -> str:
    c = re.sub(r"!\[[^\]]*\]\([^)]*\)", "[이미지]", post.get("content") or "")
    c = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", c)
    c = re.sub(r"https?://\S+", "", c)
    c = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|~<> ])", r"\1", c)
    c = re.sub(r"\n{3,}", "\n\n", c).strip() or "(본문 없음)"
    return c[:BODY_CHARS] + ("\n…(이하 생략)" if len(c) > BODY_CHARS else "")


def call_llm(api_key: str, model: str, text: str) -> tuple[dict | None, dict, str | None]:
    payload = {
        "model": model,
        "store": False,
        "temperature": 0,
        "instructions": INSTRUCTIONS,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": text}]}],
        "text": {"format": SCHEMA},
    }
    error = None
    for attempt in range(3):
        try:
            resp = requests.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=120,
            )
        except requests.RequestException as exc:
            error = f"transport:{exc.__class__.__name__}"
        else:
            if resp.status_code < 400:
                data = resp.json()
                text_out = "".join(
                    part.get("text", "")
                    for item in data.get("output", [])
                    for part in item.get("content", [])
                    if part.get("type") == "output_text"
                )
                return json.loads(text_out), data.get("usage") or {}, None
            error = f"http_{resp.status_code}:{resp.text[:200]}"
        time.sleep(2 * (attempt + 1))
    return None, {}, error


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--review", type=Path, required=True, help="build_judgment_review.py 결과")
    parser.add_argument("--posts", type=Path, required=True)
    parser.add_argument("--human-labels", type=Path, default=None, help="collect_labels.py 결과(있으면 라벨로 우선 사용)")
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--limit", type=int, required=True, help="호출할 쌍 수. OpenAI 비용이 든다")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.openai_api_key:
        parser.error("OPENAI_API_KEY 가 필요합니다.")
    posts = {p["original_url"]: p for p in json.loads(args.posts.read_text(encoding="utf-8"))}
    review = json.loads(args.review.read_text(encoding="utf-8"))
    human = {}
    if args.human_labels:
        for p in json.loads(args.human_labels.read_text(encoding="utf-8"))["pairs"]:
            if p.get("majority"):
                human[(p["a_url"], p["b_url"])] = p["majority"]

    rows = review["pairs"][: args.limit]
    records = []
    tokens = Counter()
    for n, r in enumerate(rows, 1):
        text = f"[공지 A 본문]\n{body_text(posts[r['a_url']])}\n\n[공지 B 본문]\n{body_text(posts[r['b_url']])}"
        result, usage, error = call_llm(settings.openai_api_key, args.model, text)
        tokens["input"] += int(usage.get("input_tokens") or 0)
        tokens["output"] += int(usage.get("output_tokens") or 0)
        label = human.get((r["a_url"], r["b_url"])) or r["claude_judgment"]
        records.append(
            {
                **{k: r[k] for k in ("no", "a_url", "b_url", "title_a", "title_b", "body_similarity", "bin")},
                "label": label,
                "label_source": "사람" if (r["a_url"], r["b_url"]) in human else "Claude",
                "claude_confidence": r["claude_confidence"],
                "llm_judgment": (result or {}).get("judgment"),
                "llm_reason": (result or {}).get("reason", ""),
                "error": error,
            }
        )
        if n % 25 == 0:
            print(f"  {n}/{len(rows)}")
    done = [x for x in records if x["llm_judgment"]]
    agree = [x for x in done if x["llm_judgment"] == x["label"]]
    cost = tokens["input"] / 1e6 * 0.40 + tokens["output"] / 1e6 * 1.60
    summary = {
        "model": args.model,
        "pairs": len(records),
        "failed": len(records) - len(done),
        "agreement": round(len(agree) / len(done), 3) if done else None,
        "by_label_source": {
            src: {
                "pairs": sum(1 for x in done if x["label_source"] == src),
                "agree": sum(1 for x in done if x["label_source"] == src and x["llm_judgment"] == x["label"]),
            }
            for src in ("사람", "Claude")
        },
        "by_claude_confidence": {
            c: {
                "pairs": sum(1 for x in done if x["claude_confidence"] == c),
                "agree": sum(1 for x in done if x["claude_confidence"] == c and x["llm_judgment"] == x["label"]),
            }
            for c in ("high", "low")
        },
        "confusion": dict(Counter(f"라벨 {x['label']} → LLM {x['llm_judgment']}" for x in done)),
        "tokens": dict(tokens),
        "cost_usd_list_price": round(cost, 3),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {"ran_at": datetime.now().astimezone().isoformat(timespec="seconds"), "instructions": INSTRUCTIONS,
             "summary": summary, "records": records},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print("saved", args.output)


if __name__ == "__main__":
    main()
