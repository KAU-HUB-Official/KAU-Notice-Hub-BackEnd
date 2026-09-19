"""표본 쌍을 LLM에게 판정시킨다: 두 공지를 하나로 합쳐도 되는가. merge면 실제로 합쳐 빠진 정보를 검사한다.

1. 판정: 두 본문만 보고 merge / keep_both 를 정한다. merge면 기준 본문(A 또는 B)과 덧붙일 정보를 받는다.
2. 합치기(코드): 기준 본문을 원문 그대로 두고 끝에 "추가 안내"로 덧붙일 정보를 붙인다. LLM이 본문을 새로 쓰지 않는다.
3. 검사: 버려지는 쪽 공지에 적힌 정보 중 합친 공지에 없거나 다르게 적힌 것을 LLM이 나열한다.
   하나라도 있으면 keep_both 로 바꾼다. 없으면 최종 merge 이고 합친 본문이 그대로 쓸 본문이다.
애매하면 나눈다(2026-09-19 결정). 둘 다 남기는 것도 정답이므로, 잘못 합친 경우(라벨 keep_both → merge)만 위험한 오류로 본다.

- 입력은 본문만 넘긴다. 게시판·게시일·제목·첨부 이름은 넘기지 않는다(2026-09-15 결정).
- 대상: 최종 라벨이 있는 표본 쌍 중 지금 규칙으로 정해지지 않는 쌍(classify_crosspost_pairs.py 의 "판정 필요").
- OpenAI 비용이 든다. --limit 으로 판정할 쌍 수를 반드시 정한다.

실행 (BackEnd 루트):
    .venv/bin/python -m scripts.research.judge_merge_llm \\
        --labels data/research/judgment_labels_2026-09-19.json \\
        --pairs data/research/crosspost_pairs_2026-09-15.json \\
        --posts data/research/kau_notices_clean_2026-09-15.json \\
        --limit 10 --seed 20260919 --output data/research/analysis/merge_llm_v2_2026-09-19_10.json
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests

from app.config import get_settings

PIPELINE_VERSION = "2026-09-19"  # 이 날짜로 고정한 판정 파이프라인. 지시문·합치기·검사를 바꾸면 날짜를 올린다.
BODY_CHARS = 6000
JUDGMENTS = ("merge", "keep_both")
ADDITION_HEADER = "[추가 안내]"

INSTRUCTIONS = """두 대학 공지의 본문 A, B를 비교해, 둘을 하나의 공지로 합쳐도 되는지 정한다.
합친다는 것은 한쪽 본문을 기준으로 남기고, 다른 공지에만 있는 정보를 덧붙이는 것이다.
두 공지에서 서로 다른 부분이 무엇인지를 보고 판단한다.

merge: 서로 다른 부분이 없거나, 다른 정보가 문의처·제출처·담당자·신청 링크 같은 단일 연락·접수 정보뿐이다.
  이런 정보는 합친 공지에 나란히 적으면 된다. 예: "기계공학전공 문의 …, 항공MRO전공 문의 …"
  한쪽이 다른 쪽 내용을 모두 담고 더 자세할 뿐이면 다른 부분이 아니다. 더 자세한 쪽을 기준으로 남긴다.
keep_both: 일정·장소·자격·조건·절차·금액·과목·선발 인원처럼 공지의 핵심 내용이 서로 다르다.
  이런 공지를 합치면 한 공지를 보던 사람이 자기와 관계없는 내용을 읽어야 하거나,
  어느 내용이 자기에게 해당하는지 헷갈린다.

애매하면 keep_both로 한다. merge는 합쳐도 지장이 없다고 확신할 때만 고른다.

merge이면 기준 본문(A 또는 B)과 덧붙일 정보를 적는다. 덧붙일 정보는 다른 공지의 문장을 그대로 옮기고,
요약하거나 새 문장을 쓰지 않는다. 본문에 없는 내용은 만들지 않는다."""

SCHEMA = {
    "type": "json_schema",
    "name": "merge_judgment",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["judgment", "reason", "base", "additions"],
        "properties": {
            "judgment": {"type": "string", "enum": list(JUDGMENTS)},
            "reason": {"type": "string", "description": "판단 근거 한 문장"},
            "base": {"type": "string", "enum": ["A", "B", "none"], "description": "merge일 때 남길 본문. keep_both면 none"},
            "additions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "merge일 때 기준 본문에 덧붙일 정보. 없으면 빈 목록",
            },
        },
    },
}

CHECK_INSTRUCTIONS = """원래 공지와 합친 공지를 비교한다.
원래 공지에 적혀 있는 정보(일정·장소·대상·자격·신청 방법·제출처·문의처·금액 등) 가운데
합친 공지에 없거나 다르게 적힌 것만 나열한다.
원래 공지에 없는 항목, 합친 공지에만 있는 정보, 표현만 다르고 뜻이 같은 것은 넣지 않는다. 없으면 빈 목록이다."""

CHECK_SCHEMA = {
    "type": "json_schema",
    "name": "merge_check",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["missing"],
        "properties": {"missing": {"type": "array", "items": {"type": "string"}}},
    },
}


def body_text(post: dict) -> str:
    c = re.sub(r"!\[[^\]]*\]\([^)]*\)", "[이미지]", post.get("content") or "")
    c = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", c)
    c = re.sub(r"https?://\S+", "", c)
    c = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|~<> ])", r"\1", c)
    c = re.sub(r"\n{3,}", "\n\n", c).strip() or "(본문 없음)"
    return c[:BODY_CHARS] + ("\n…(이하 생략)" if len(c) > BODY_CHARS else "")


def merged_body(base_text: str, additions: list[str]) -> str:
    """기준 본문은 그대로 두고, 덧붙일 정보가 있으면 끝에 [추가 안내]로 붙인다."""
    items = [a.strip() for a in additions if a.strip()]
    return base_text + (f"\n\n{ADDITION_HEADER}\n" + "\n".join(f"- {a}" for a in items) if items else "")


def final_judgment(judgment: str | None, base: str | None, missing: list[str] | None) -> str | None:
    """merge 는 기준 본문이 있고 검사에서 빠진 정보가 없을 때만 남긴다. 그 밖에는 나눈다(애매하면 나눈다)."""
    if judgment is None:
        return None
    if judgment == "merge" and base in ("A", "B") and missing is not None and not missing:
        return "merge"
    return "keep_both"


def call_llm(api_key: str, model: str, instructions: str, schema: dict, text: str) -> tuple[dict | None, dict, str | None]:
    payload = {
        "model": model,
        "store": False,
        "temperature": 0,
        "instructions": instructions,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": text}]}],
        "text": {"format": schema},
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
    parser.add_argument("--labels", type=Path, required=True, help="finalize_judgment_labels.py 결과")
    parser.add_argument("--pairs", type=Path, required=True, help="classify_crosspost_pairs.py 결과(판정 필요 쌍만 고른다)")
    parser.add_argument("--posts", type=Path, required=True)
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--limit", type=int, required=True, help="판정할 쌍 수. OpenAI 비용이 든다")
    parser.add_argument("--seed", type=int, default=None, help="쌍을 무작위로 고를 때 시드(없으면 표본 순서대로)")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.openai_api_key:
        parser.error("OPENAI_API_KEY 가 필요합니다.")
    posts = {p["original_url"]: p for p in json.loads(args.posts.read_text(encoding="utf-8"))}
    steps = {
        frozenset((p["a_url"], p["b_url"])): p["step"]
        for p in json.loads(args.pairs.read_text(encoding="utf-8"))["pairs"]
    }
    labeled = json.loads(args.labels.read_text(encoding="utf-8"))["pairs"]
    targets = [r for r in labeled if r["label"] and steps.get(frozenset((r["a_url"], r["b_url"]))) == "판정 필요"]
    print(f"라벨 {len(labeled)}쌍 중 판정 필요로 남은 쌍 {len(targets)}")
    if args.seed is not None:
        random.Random(args.seed).shuffle(targets)
    rows = targets[: args.limit]

    key = settings.openai_api_key
    records, tokens, calls = [], Counter(), Counter()
    for n, r in enumerate(rows, 1):
        texts = {"A": body_text(posts[r["a_url"]]), "B": body_text(posts[r["b_url"]])}
        judged, usage, error = call_llm(
            key, args.model, INSTRUCTIONS, SCHEMA, f"[공지 A 본문]\n{texts['A']}\n\n[공지 B 본문]\n{texts['B']}"
        )
        calls["judge"] += 1
        tokens["input"] += int(usage.get("input_tokens") or 0)
        tokens["output"] += int(usage.get("output_tokens") or 0)
        judged = judged or {}
        record = {
            **{k: r[k] for k in ("no", "a_url", "b_url", "title_a", "title_b", "body_similarity", "bin")},
            "label": r["label"],
            "label_source": "Claude" if r["label_source"] == "Claude" else "사람",
            "llm_judgment": judged.get("judgment"),
            "llm_reason": judged.get("reason", ""),
            "base": judged.get("base"),
            "additions": judged.get("additions") or [],
            "merged_body": None,
            "missing": [],
            "final_judgment": judged.get("judgment"),
            "error": error,
        }
        if judged.get("judgment") == "merge" and judged.get("base") in ("A", "B"):
            base = judged["base"]
            dropped = "B" if base == "A" else "A"
            merged = merged_body(texts[base], record["additions"])
            checked, usage, check_error = call_llm(
                key, args.model, CHECK_INSTRUCTIONS, CHECK_SCHEMA, f"[원래 공지]\n{texts[dropped]}\n\n[합친 공지]\n{merged}"
            )
            calls["check"] += 1
            tokens["input"] += int(usage.get("input_tokens") or 0)
            tokens["output"] += int(usage.get("output_tokens") or 0)
            record["merged_body"] = merged
            record["missing"] = (checked or {}).get("missing") or []
            if checked is None:
                record["error"] = check_error
                record["final_judgment"] = None
            else:
                record["final_judgment"] = final_judgment("merge", base, record["missing"])
        elif judged.get("judgment"):
            record["final_judgment"] = final_judgment(judged["judgment"], judged.get("base"), None)
        records.append(record)
        if n % 25 == 0:
            print(f"  {n}/{len(rows)}")

    done = [x for x in records if x["final_judgment"]]
    kb = [x for x in done if x["label"] == "keep_both"]
    cost = tokens["input"] / 1e6 * 0.40 + tokens["output"] / 1e6 * 1.60
    summary = {
        "model": args.model,
        "pairs": len(records),
        "failed": len(records) - len(done),
        "llm_calls": dict(calls),
        "agreement_raw": round(sum(x["llm_judgment"] == x["label"] for x in done) / len(done), 3) if done else None,
        "agreement_final": round(sum(x["final_judgment"] == x["label"] for x in done) / len(done), 3) if done else None,
        "keep_both_recall_final": round(sum(x["final_judgment"] == "keep_both" for x in kb) / len(kb), 3) if kb else None,
        "wrong_merge_final": sum(1 for x in kb if x["final_judgment"] == "merge"),
        "merged_final": sum(1 for x in done if x["final_judgment"] == "merge"),
        "merge_yield_final": (
            f'{sum(1 for x in done if x["label"] == "merge" and x["final_judgment"] == "merge")}'
            f'/{sum(1 for x in done if x["label"] == "merge")}'
        ),
        "merge_downgraded_by_check": sum(1 for x in done if x["llm_judgment"] == "merge" and x["final_judgment"] == "keep_both"),
        "by_label_source": {
            src: {
                "pairs": sum(1 for x in done if x["label_source"] == src),
                "agree_final": sum(1 for x in done if x["label_source"] == src and x["final_judgment"] == x["label"]),
            }
            for src in ("사람", "Claude")
        },
        "confusion_final": dict(Counter(f"라벨 {x['label']} → 최종 {x['final_judgment']}" for x in done)),
        "tokens": dict(tokens),
        "cost_usd_list_price": round(cost, 3),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "pipeline_version": PIPELINE_VERSION,
                "instructions": INSTRUCTIONS,
                "check_instructions": CHECK_INSTRUCTIONS,
                "summary": summary,
                "records": records,
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
