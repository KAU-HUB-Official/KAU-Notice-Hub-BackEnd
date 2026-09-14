"""챗봇 분기(triage) 검증 runner.

질문마다 실제 운영 검색 경로(`_retrieve_references`)를 태워, 모델이 고른 분기가 기대한
분기와 같은지 확인한다. 답변 생성은 하지 않는다 — 분기는 답변 전에 이미 정해지므로
답변까지 만들면 비용만 늘고 검증 대상은 같다.

분기 종류 (RetrievalTrace.mode)
- search        : 공지를 찾아야 답할 수 있는 질문으로 판정 → 추출한 키워드로 검색
- out_of_domain : KAU 공지와 무관하다고 판정 → 가드 문구로 거부
- legacy        : triage LLM 호출/파싱 실패 → 질문 원문 그대로 검색 (분기 실패 신호)
- history       : 이전 대화 재가공. 단일턴에선 나오면 안 된다(대화가 없으면 search로 강등)

주의: `_retrieve_references` 가 돌려주는 mode 문자열은 legacy 도 "search" 로 보인다.
게다가 legacy 는 fallback_to_latest=True 라 검색어가 안 맞아도 최신 공지로 채워져
"결과가 나온 정상 검색"처럼 보인다. 그래서 판정은 반드시 trace.mode 로 한다.

같이 기록하는 것 (= grounding 검증: RAGAS 가 이 질문을 채점할 수 있는가)
- hits : 검색 후보 수. 0 이면 DB 에 근거 공지가 없는 질문이다.
- kept : rerank 후 남은 공지 수. ragas_runner 는 kept == 0 이면 샘플을 스킵한다.

실행 (triage·rerank 에 OpenAI 호출이 들어간다. out_of_domain 은 triage 1회로 끝난다):
   RAG_ENABLED=true OPENAI_API_KEY=... .venv/bin/python -m tests.eval.branch_runner
   ... -m tests.eval.branch_runner path/a.yml path/b.yml    # 입력 파일 직접 지정

입력 YAML 은 두 형식을 모두 받는다.
- 그룹 dict : {rag_quality: [...], robustness: [...]}   (datasets/collected_v1.yml)
- 평면 list : [...]                                      (ragas_cases.yml)
각 항목의 expect 가 없으면 "search" 로 본다. 결과는 data/branch_runs/<실행시각>.json 에 남는다.
검색은 평가용 고정 스냅샷(tests/eval/snapshot.py)의 DB와 기준일로 돈다.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from app.chat_service import _retrieve_references
from app.config import get_settings
from app.service import NoticeService
from app.sqlite_repository import SqliteNoticeRepository
from tests.eval.snapshot import EvalSnapshot, load_snapshot

# ragas_runner 와 같은 파서를 써야 "RAGAS 채점 가능" 판정이 실제 RAGAS 실행과 어긋나지 않는다.
from tests.eval.ragas_runner import _filters_from_case

DATASET_DIR = Path(__file__).parent / "datasets"
DEFAULT_CASE_PATHS = [
    DATASET_DIR / "collected_v1.yml",
    DATASET_DIR / "branch_negatives.yml",
]
DEFAULT_DUMP_DIR = Path("data/branch_runs")

# 기대값으로 쓸 수 있는 분기. legacy(분기 실패)·history(단일턴 불가)는 정답이 될 수 없다.
EXPECTED_BRANCHES = ("search", "out_of_domain")
ACTUAL_BRANCHES = ("search", "out_of_domain", "legacy", "history", "error")


def _progress(message: str) -> None:
    """진행 로그는 stderr 로 보내 stdout 의 최종 보고서만 깨끗하게 캡처되게 한다."""
    print(message, file=sys.stderr, flush=True)


def load_cases(paths: list[Path]) -> list[dict[str, Any]]:
    """YAML 파일들에서 검증 케이스를 모은다. expect 가 없으면 "search"."""
    cases: list[dict[str, Any]] = []
    for path in paths:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        groups = data.items() if isinstance(data, dict) else [("cases", data)]
        for group, items in groups:
            for item in items or []:
                expect = item.get("expect", "search")
                if expect not in EXPECTED_BRANCHES:
                    raise ValueError(
                        f"{path.name}:{item.get('id')} expect={expect!r} — "
                        f"{EXPECTED_BRANCHES} 중 하나여야 합니다."
                    )
                cases.append(
                    {
                        "id": item["id"],
                        "question": item["question"],
                        "expect": expect,
                        "filters": item.get("filters") or {},
                        "decoded": item.get("decoded"),
                        "group": group,
                        "source": path.name,
                    }
                )
    dupes = sorted(i for i, n in Counter(c["id"] for c in cases).items() if n > 1)
    if dupes:
        raise ValueError(f"케이스 id 중복: {dupes}")
    return cases


async def run_case(
    service: NoticeService, case: dict[str, Any], today: date | None = None
) -> dict[str, Any]:
    """케이스 하나를 운영 검색 경로에 태워 분기와 검색 결과를 기록한다."""
    result: dict[str, Any] = dict(case)
    try:
        notices, _references, _returned_mode, trace = await _retrieve_references(
            service, case["question"].strip(), _filters_from_case(case), today=today
        )
    except Exception as exc:  # noqa: BLE001 - 한 케이스 실패로 전체 실행을 멈추지 않는다
        result.update(
            actual="error",
            match=False,
            error=f"{type(exc).__name__}: {exc}",
            hits=0,
            kept=0,
            ragas_ready=False,
        )
        return result

    result.update(
        actual=trace.mode,
        match=trace.mode == case["expect"],
        keywords=trace.triage_keywords,
        search_query=trace.search_query,
        hits=len(trace.candidates),
        kept=len(notices),
        rerank_outcome=trace.rerank_outcome,
        # ragas_runner._collect_sample 과 같은 조건. legacy 는 반환 mode 가 search 여도 스킵된다.
        ragas_ready=trace.mode == "search" and bool(notices),
        triage_raw=trace.triage_raw,
        latency_ms=trace.latency_ms,
    )
    return result


async def run_all(
    service: NoticeService, cases: list[dict[str, Any]], today: date | None = None
) -> list[dict[str, Any]]:
    """케이스를 순서대로 실행한다(병렬 호출 없이 한 건씩 — 결과 순서와 로그를 단순하게)."""
    results: list[dict[str, Any]] = []
    total = len(cases)
    for index, case in enumerate(cases, start=1):
        result = await run_case(service, case, today)
        mark = "OK  " if result["match"] else "MISS"
        _progress(
            f"  [{index}/{total}] {mark} {case['id']}: "
            f"기대 {case['expect']} → 실제 {result['actual']} (검색 {result['hits']}건)"
        )
        results.append(result)
    return results


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """혼동행렬과 오류 유형별 건수를 계산한다."""
    confusion: dict[str, Counter[str]] = {e: Counter() for e in EXPECTED_BRANCHES}
    for r in results:
        confusion[r["expect"]][r["actual"]] += 1

    total = len(results)
    matched = sum(1 for r in results if r["match"])
    search_expected = [r for r in results if r["expect"] == "search"]
    return {
        "total": total,
        "matched": matched,
        "accuracy": matched / total if total else 0.0,
        # 검색해야 하는데 거부함
        "false_reject": confusion["search"]["out_of_domain"],
        # 거부해야 하는데 검색함. legacy 도 결국 원문으로 검색하므로 포함한다.
        "false_search": confusion["out_of_domain"]["search"]
        + confusion["out_of_domain"]["legacy"],
        "legacy": sum(c["legacy"] for c in confusion.values()),
        "errors": sum(c["error"] for c in confusion.values()),
        "confusion": {e: dict(c) for e, c in confusion.items()},
        # grounding: search 기대 케이스 중 RAGAS 에서 실제로 채점될 수 있는 수
        "search_expected": len(search_expected),
        "ragas_ready": sum(1 for r in search_expected if r["ragas_ready"]),
        "zero_hits": [
            r["id"]
            for r in search_expected
            if r["actual"] in ("search", "legacy") and r["hits"] == 0
        ],
        "rerank_dropped": [
            r["id"] for r in search_expected if r["hits"] > 0 and r["kept"] == 0
        ],
    }


def format_report(results: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    s = summary
    corner = "기대 \\ 실제"  # f-string 중괄호 안 역슬래시는 3.12 미만에서 문법 오류라 밖에서 만든다
    lines = [
        "=== 분기 검증 결과 ===",
        f"전체 {s['total']}건 중 일치 {s['matched']}건 (정확도 {s['accuracy']:.1%})",
        f"  오거부 (검색해야 하는데 거부)  : {s['false_reject']}건",
        f"  오검색 (거부해야 하는데 검색)  : {s['false_search']}건",
        f"  triage 실패 → legacy          : {s['legacy']}건",
        f"  실행 에러                      : {s['errors']}건",
        "",
        "혼동행렬 (행 = 기대 분기, 열 = 실제 분기)",
        f"{corner:<14}" + "".join(f"{a:>15}" for a in ACTUAL_BRANCHES),
    ]
    for expect in EXPECTED_BRANCHES:
        row = s["confusion"].get(expect, {})
        lines.append(
            f"{expect:<14}" + "".join(f"{row.get(a, 0):>15}" for a in ACTUAL_BRANCHES)
        )

    lines += [
        "",
        f"RAGAS 채점 가능 (search 기대 {s['search_expected']}건 기준): {s['ragas_ready']}건",
        f"  검색 0건 — 근거 공지 없음 : {', '.join(s['zero_hits']) or '없음'}",
        f"  rerank 후 0건             : {', '.join(s['rerank_dropped']) or '없음'}",
    ]

    misses = [r for r in results if not r["match"]]
    if misses:
        lines += ["", "불일치 상세"]
        for r in misses:
            lines.append(f"  [{r['id']}] 기대 {r['expect']} → 실제 {r['actual']}")
            lines.append(f"      질문   : {r['question']!r}")
            if r.get("decoded"):
                lines.append(f"      해독   : {r['decoded']}")
            if r.get("keywords"):
                lines.append(f"      키워드 : {r['keywords']}")
            if r.get("error"):
                lines.append(f"      에러   : {r['error']}")
            elif r.get("triage_raw"):
                lines.append(f"      triage : {r['triage_raw'][:160]}")
    return "\n".join(lines)


def write_dump(
    results: list[dict[str, Any]],
    summary: dict[str, Any],
    path: Path,
    snapshot: EvalSnapshot,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "snapshot": {"name": snapshot.name, "reference_date": snapshot.reference_date.isoformat()},
        "summary": summary,
        "results": results,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _require_live_triage() -> None:
    """triage 가 실제로 호출되는 설정인지 확인한다.

    셋 중 하나라도 꺼져 있으면 `_retrieve_references` 가 triage 를 건너뛰고 전부 legacy
    (질문 원문 검색)로 떨어진다. 그러면 모든 질문이 "검색됨"으로 보여 검증 결과가
    무의미해지므로, 돌리기 전에 막는다.
    """
    settings = get_settings()
    missing = []
    if not settings.rag_enabled:
        missing.append("RAG_ENABLED=true")
    if not settings.openai_api_key:
        missing.append("OPENAI_API_KEY")
    if not settings.rag_query_extraction_enabled:
        missing.append("RAG_QUERY_EXTRACTION_ENABLED=true")
    if missing:
        raise SystemExit(
            "분기 검증에는 실제 triage 호출이 필요합니다. 설정 필요: " + ", ".join(missing)
        )


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    paths = [Path(a) for a in args] or DEFAULT_CASE_PATHS
    cases = load_cases(paths)
    snapshot = load_snapshot()
    _require_live_triage()

    _progress(f"[분기 검증] {len(cases)}건 — {', '.join(p.name for p in paths)}")
    _progress(f"[스냅샷] {snapshot.name} (기준일 {snapshot.reference_date})")
    service = NoticeService(SqliteNoticeRepository(snapshot.db_path))
    results = asyncio.run(run_all(service, cases, snapshot.reference_date))
    summary = summarize(results)
    print(format_report(results, summary))

    path = DEFAULT_DUMP_DIR / f"{datetime.now():%Y-%m-%d_%H%M%S}.json"
    write_dump(results, summary, path, snapshot)
    _progress(f"[저장] 케이스별 분기·키워드·검색 결과를 {path} 에 기록했습니다.")


if __name__ == "__main__":
    main()
