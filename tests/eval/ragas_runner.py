"""RAGAS 기반 RAG 품질 평가 runner (LLM-as-judge).

라벨(모범답안)이 필요 없는 2개 지표만 측정한다 (ragas 0.4 collections API):

- faithfulness                         : 답변이 검색된 context에 충실한가 (환각 여부)
- context_precision_without_reference  : 검색된 context가 질문에 관련 있나 (노이즈)

answer_relevancy는 측정하지 않는다. 답변에서 거꾸로 만든 질문과 원 질문의 임베딩
유사도로 채점하는데, 공지에 없는 날짜를 추측하지 않고 "명시되어 있지 않다"고 답하면
얼버무린 답변으로 보고 0점을 주고, 기간·대상·방법을 목록으로 정리한 답변은 거꾸로
만든 질문이 원 질문과 달라져 점수가 낮게 나온다. 질문에 답했는지는 사람이 0/1로
판정한다.

채점관은 ragas native `llm_factory`(InstructorLLM)를 쓰고, 샘플마다 collections
메트릭의 `ascore()`로 채점한다.

각 지표는 OpenAI를 채점관으로 호출하므로 **비용이 발생한다**. 그래서 평가셋의
질문마다 실제 `/api/chat` 파이프라인(triage → 검색 → rerank → 답변 생성)을 한 번
돌려 (question, retrieved_contexts, response)를 모은 뒤 RAGAS로 채점한다.

전제: `RAG_ENABLED=true` 와 `OPENAI_API_KEY` 가 설정돼 있어야 한다. 채점관 LLM은
`OPENAI_MODEL`(기본 gpt-4.1-mini)을 재사용한다.

실행:

   RAG_ENABLED=true OPENAI_API_KEY=... .venv/bin/python -m tests.eval.ragas_runner

평가 질문은 RAGAS 전용 셋 tests/eval/ragas_cases.yml 을 쓴다(question/filters만
사용). 운영 데이터(data/kau_notice_hub.db)가 있어야 검색이 동작한다.
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def _progress(message: str) -> None:
    """진행 상황을 stderr로 즉시 출력한다.

    stdout에는 최종 보고서만 나가게 해서 `... | tee report.txt`가 깨끗하게 캡처되도록
    진행 로그는 stderr로 분리하고, flush로 한 줄씩 바로 보이게 한다(채점 단계마다
    OpenAI 호출이 길어 버퍼링되면 한참 깜깜해 보인다).
    """
    print(message, file=sys.stderr, flush=True)

from app.chat_service import (
    CONTEXT_CONTENT_CHARS,
    _generate_with_openai,
    _retrieve_references,
    truncate,
)
from app.config import get_settings
from app.dependencies import _build_repository
from app.schemas import Notice
from app.service import NoticeQuery, NoticeService

CASES_PATH = Path(__file__).parent / "ragas_cases.yml"

# 평가 1회의 (질문·필터·검색 context·생성 답변·점수)를 남기는 JSON 아티팩트.
# 실행마다 data/ragas_runs/<run_ts>.json 으로 남겨 과거 실행을 덮어쓰지 않는다(회귀
# 추적). data/ 는 .gitignore 대상이라 이 상세 로그는 로컬 전용이고, 커밋되는 요약
# 이력은 eval_history.csv 로 따로 남긴다. RAGAS_DUMP_PATH로 특정 경로를 강제하거나
# 빈 문자열로 저장을 끌 수 있다. 점수만으론 낮은 케이스의 원인을 못 보므로 저장한다.
DEFAULT_DUMP_DIR = "data/ragas_runs"

# 실행별 요약 점수 이력(한 실행 = 한 행). data/ 밖(tests/eval/)에 두어 git으로 추적하고,
# 이걸로 모델·프롬프트·리트리버 변경 전후를 비교한다. 상세 샘플은 위 dump에만 남는다.
HISTORY_CSV_PATH = Path(__file__).parent / "eval_history.csv"

# RAGAS collections 메트릭 이름 (ragas 0.4.x).
METRIC_NAMES = [
    "faithfulness",
    "context_precision_without_reference",
]


def _load_cases() -> list[dict[str, Any]]:
    with CASES_PATH.open("r", encoding="utf-8") as f:
        cases = yaml.safe_load(f)
    if not isinstance(cases, list):
        raise RuntimeError("ragas_cases.yml은 list여야 합니다.")
    return cases


def _filters_from_case(case: dict[str, Any]) -> NoticeQuery:
    filters = case.get("filters") or {}
    return NoticeQuery(
        audience_group=filters.get("audience_group"),
        source_group=filters.get("source_group"),
        source=filters.get("source"),
        category=filters.get("category"),
        department=filters.get("department"),
    )


def _contexts_from_notices(notices: list[Notice]) -> list[str]:
    """검색된 공지를 RAGAS retrieved_contexts(문자열 리스트)로 변환.

    한 공지 = 한 context chunk. content를 build_context와 같은 길이(CONTEXT_CONTENT_CHARS)로
    자른다. content가 비면 제목으로 폴백하고, 그래도 비면 제외한다. 이미지뿐인 공지는
    enrichment가 content를 실제 텍스트로 채우므로 content 하나면 충분하다(summary 필드
    제거 후 읽는 본문은 content로 단일화됨).
    """
    contexts: list[str] = []
    for notice in notices:
        text = (notice.content or "").strip()
        text = truncate(text, CONTEXT_CONTENT_CHARS) if text else (notice.title or "").strip()
        if text:
            contexts.append(text)
    return contexts


async def _collect_sample(
    service: NoticeService, case: dict[str, Any]
) -> tuple[dict[str, Any] | None, str]:
    """케이스 하나를 실제 chat 파이프라인에 돌려 RAGAS 샘플 dict를 만든다.

    채점할 수 없으면 (None, 스킵 사유)를 반환한다.

    분기는 반환 mode가 아니라 trace.mode로 판정한다. 분기 LLM이 실패한 legacy 경로도
    반환 mode는 "search"이고, 질문 원문 검색에 최신 공지 폴백까지 붙어 결과가 채워지므로
    반환 mode만 보면 운영 경로 샘플과 구분되지 않는다.
    """
    question = case["question"]
    filters = _filters_from_case(case)

    notices, _references, _mode, trace = await _retrieve_references(
        service, question, filters
    )
    if trace.mode == "legacy":
        return None, "분기 실패(legacy)"
    if trace.mode != "search":
        return None, f"분기 {trace.mode}"
    if not notices:
        return None, "검색 0건"

    contexts = _contexts_from_notices(notices)
    if not contexts:
        return None, "context 없음"

    result = await _generate_with_openai(question, filters, notices)
    if result is None:
        return None, "답변 생성 실패"
    answer, _model = result

    sample = {
        "case_id": case.get("id", question[:20]),
        "user_input": question,
        "filters": case.get("filters") or {},
        "retrieved_contexts": contexts,
        "response": answer,
    }
    return sample, ""


async def collect_samples() -> tuple[list[dict[str, Any]], list[str]]:
    """평가셋 전체를 파이프라인에 돌려 RAGAS 샘플 리스트와 스킵 사유를 모은다."""
    service = NoticeService(_build_repository())
    cases = _load_cases()
    total = len(cases)
    samples: list[dict[str, Any]] = []
    skipped: list[str] = []
    _progress(f"[1/2 수집] {total}개 질문을 chat 파이프라인에 돌립니다 (질문당 OpenAI 호출 다수)…")
    for index, case in enumerate(cases, start=1):
        case_id = str(case.get("id", case.get("question", "?")))
        _progress(f"  [{index}/{total}] {case_id} … triage→검색→rerank→답변 생성")
        sample, reason = await _collect_sample(service, case)
        if sample is None:
            skipped.append(f"{case_id}({reason})")
            _progress(f"  [{index}/{total}] {case_id} → 스킵: {reason}")
        else:
            samples.append(sample)
            _progress(
                f"  [{index}/{total}] {case_id} → context {len(sample['retrieved_contexts'])}건 수집 완료"
            )
    _progress(f"[1/2 수집] 완료: 채점 대상 {len(samples)}건 / 스킵 {len(skipped)}건")
    return samples, skipped


def _require_openai() -> None:
    settings = get_settings()
    if not settings.rag_enabled:
        raise RuntimeError(
            "RAG_ENABLED=true 가 필요합니다. 비활성 상태에서는 답변이 local "
            "fallback이라 RAGAS 채점 대상이 아닙니다."
        )
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY 가 필요합니다 (채점관 LLM 호출용).")


async def _safe_score(coro: Any) -> float:
    """메트릭 ascore 코루틴을 await해 float 점수를 뽑는다. 실패하면 NaN."""
    try:
        result = await coro
    except Exception:  # noqa: BLE001 - 한 샘플 채점 실패가 전체를 멈추지 않게 한다
        logger.warning("ragas: ascore failed", exc_info=True)
        return float("nan")
    try:
        return float(result.value)
    except (TypeError, ValueError):
        return float("nan")


async def _score_samples(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """수집한 샘플을 collections 메트릭의 ascore로 채점해 행 리스트를 만든다.

    ragas import는 함수 안에서 한다 — eval extra가 설치되지 않은 환경(기본 CI)에서
    이 모듈을 import만 해도 깨지지 않게 한다.
    """
    # collections 메트릭의 ascore()는 agenerate()를 호출하므로 async 클라이언트가 필요하다
    # (동기 OpenAI 클라이언트면 "Cannot use agenerate() with a synchronous client" 에러).
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.metrics.collections import (
        ContextPrecisionWithoutReference,
        Faithfulness,
    )

    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    # 기본 max_tokens=1024는 우리 context(공지 본문 다수)·답변 길이에선 구조화 출력이
    # 잘려 IncompleteOutputException이 난다. ragas 권장대로 4096으로 올린다.
    llm = llm_factory(settings.openai_model, client=client, max_tokens=4096)

    faith = Faithfulness(llm=llm)
    ctx_prec = ContextPrecisionWithoutReference(llm=llm)

    total = len(samples)
    _progress(f"[2/2 채점] {total}개 샘플을 RAGAS 2개 지표로 채점합니다 (지표마다 OpenAI 호출)…")
    rows: list[dict[str, Any]] = []
    for index, sample in enumerate(samples, start=1):
        ui = sample["user_input"]
        resp = sample["response"]
        ctxs = sample["retrieved_contexts"]
        case_id = sample["case_id"]
        _progress(f"  [{index}/{total}] {case_id} … 채점 중")
        # 샘플당 2개 지표를 동시에(과한 burst 없이) 채점한다.
        faith_score, ctx_score = await asyncio.gather(
            _safe_score(faith.ascore(user_input=ui, response=resp, retrieved_contexts=ctxs)),
            _safe_score(
                ctx_prec.ascore(user_input=ui, response=resp, retrieved_contexts=ctxs)
            ),
        )
        _progress(
            f"  [{index}/{total}] {case_id} → "
            f"faith={faith_score:.3f} ctx_prec={ctx_score:.3f}"
        )
        rows.append(
            {
                "case_id": case_id,
                "faithfulness": faith_score,
                "context_precision_without_reference": ctx_score,
            }
        )
    _progress("[2/2 채점] 완료. 아래에 최종 보고서를 출력합니다.")
    return rows


def run_ragas(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """수집한 샘플을 채점해 케이스별 점수 행 리스트를 반환한다."""
    return asyncio.run(_score_samples(samples))


def summarize(rows: list[dict[str, Any]]) -> dict[str, float]:
    """채점 행에서 지표별 평균(NaN 제외)을 뽑는다."""
    summary: dict[str, float] = {}
    for name in METRIC_NAMES:
        values = [
            r[name]
            for r in rows
            if name in r and isinstance(r[name], float) and not math.isnan(r[name])
        ]
        if values:
            summary[name] = sum(values) / len(values)
    return summary


def valid_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """지표별로 실제 채점에 성공한(NaN이 아닌) 샘플 수.

    summarize()의 평균은 채점 실패(NaN)를 뺀 값이라, 이 수를 함께 보지 않으면 일부
    샘플만으로 낸 평균이 전체 평균처럼 보인다.
    """
    return {
        name: sum(
            1
            for r in rows
            if isinstance(r.get(name), float) and not math.isnan(r[name])
        )
        for name in METRIC_NAMES
    }


def _clean_score(value: Any) -> float | None:
    """NaN(채점 실패)을 JSON에 유효한 null로 바꾼다."""
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _run_timestamp() -> str:
    """실행 식별용 타임스탬프(로컬 시각). dump 파일명과 이력 행에 함께 쓴다."""
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def dump_path(run_ts: str | None = None) -> Path | None:
    """아티팩트 저장 경로.

    RAGAS_DUMP_PATH가 설정돼 있으면 그 경로(빈 문자열이면 None=저장 비활성)를 쓰고,
    없으면 data/ragas_runs/<run_ts>.json 으로 실행마다 새 파일에 남긴다(덮어쓰기 방지).
    """
    raw = os.environ.get("RAGAS_DUMP_PATH")
    if raw is not None:
        raw = raw.strip()
        return Path(raw) if raw else None
    return Path(DEFAULT_DUMP_DIR) / f"{run_ts or _run_timestamp()}.json"


def write_run_artifact(
    samples: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    skipped: list[str],
    path: Path,
) -> None:
    """샘플(질문·필터·context·답변)과 점수를 case_id로 합쳐 JSON으로 저장한다."""
    scores = {r["case_id"]: r for r in rows}
    records = []
    for sample in samples:
        row = scores.get(sample["case_id"], {})
        records.append(
            {
                "case_id": sample["case_id"],
                "user_input": sample["user_input"],
                "filters": sample.get("filters") or {},
                "response": sample["response"],
                "faithfulness": _clean_score(row.get("faithfulness")),
                "context_precision_without_reference": _clean_score(
                    row.get("context_precision_without_reference")
                ),
                "retrieved_contexts": sample["retrieved_contexts"],
            }
        )
    payload = {
        "summary": summarize(rows),
        "valid_counts": valid_counts(rows),
        "scored": len(records),
        "skipped": skipped,
        "samples": records,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def append_history(
    rows: list[dict[str, Any]],
    skipped: list[str],
    *,
    run_ts: str,
    judge_model: str,
    dump: Path | None,
) -> None:
    """실행 요약 한 행을 eval_history.csv에 append 한다(회귀 추적용, git 추적 대상).

    개별 케이스 점수가 아니라 지표 평균과 지표별 채점 성공 수(`<지표>_n`)만 남긴다(상세는
    dump 아티팩트에 있음). 파일이 없으면 헤더를 먼저 쓴다. 어떤 채점관으로 낸 점수인지
    함께 기록해, 채점 설정이 다른 실행끼리 잘못 비교하지 않도록 한다.
    """
    summary = summarize(rows)
    fields = [
        "run_ts",
        "judge_model",
        "scored",
        "skipped",
        *METRIC_NAMES,
        *(f"{name}_n" for name in METRIC_NAMES),
        "dump",
    ]
    record = {
        "run_ts": run_ts,
        "judge_model": judge_model,
        "scored": len(rows),
        "skipped": len(skipped),
        "dump": str(dump) if dump is not None else "",
    }
    counts = valid_counts(rows)
    for name in METRIC_NAMES:
        record[name] = f"{summary[name]:.4f}" if name in summary else ""
        record[f"{name}_n"] = counts[name]

    is_new = not HISTORY_CSV_PATH.exists()
    HISTORY_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_CSV_PATH.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if is_new:
            writer.writeheader()
        writer.writerow(record)


def format_report(rows: list[dict[str, Any]], skipped: list[str]) -> str:
    short = {
        "faithfulness": "faith",
        "context_precision_without_reference": "ctx_prec",
    }
    header = f"{'case':10s} " + " ".join(f"{short[c]:>9s}" for c in METRIC_NAMES)
    lines = [header, "-" * len(header)]
    for row in rows:
        cells = " ".join(f"{row.get(c, float('nan')):9.3f}" for c in METRIC_NAMES)
        lines.append(f"{str(row['case_id'])[:10]:10s} {cells}")

    summary = summarize(rows)
    lines.append("-" * len(header))
    avg_cells = " ".join(f"{summary.get(c, float('nan')):9.3f}" for c in METRIC_NAMES)
    lines.append(f"{'AVG':10s} {avg_cells}")
    counts = valid_counts(rows)
    n_cells = " ".join(f"{counts[c]:>9d}" for c in METRIC_NAMES)
    lines.append(f"{'n':10s} {n_cells}")
    lines.append("")
    lines.append(f"채점 샘플 {len(rows)}건 / 스킵 {len(skipped)}건")
    partial = [c for c in METRIC_NAMES if counts[c] < len(rows)]
    if partial:
        lines.append(
            "주의: 채점 실패(NaN)가 있어 평균은 성공한 샘플로만 계산됨 — "
            + ", ".join(f"{c} {counts[c]}/{len(rows)}" for c in partial)
        )
    if skipped:
        lines.append(f"스킵: {', '.join(skipped)}")
    return "\n".join(lines)


def main() -> None:
    _require_openai()
    samples, skipped = asyncio.run(collect_samples())
    if not samples:
        print("채점할 search 분기 샘플이 없습니다. 스킵:", ", ".join(skipped))
        return
    rows = run_ragas(samples)
    print(format_report(rows, skipped))

    settings = get_settings()
    run_ts = _run_timestamp()

    path = dump_path(run_ts)
    if path is not None:
        write_run_artifact(samples, rows, skipped, path)
        _progress(f"[저장] 질문·필터·context·답변·점수를 {path} 에 기록했습니다.")

    append_history(
        rows,
        skipped,
        run_ts=run_ts,
        judge_model=settings.openai_model,
        dump=path,
    )
    _progress(f"[이력] 요약 점수를 {HISTORY_CSV_PATH} 에 append 했습니다.")


if __name__ == "__main__":
    main()
