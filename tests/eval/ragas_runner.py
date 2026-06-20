"""RAGAS 기반 RAG 품질 평가 runner (LLM-as-judge).

라벨(모범답안)이 필요 없는 3개 지표만 측정한다:

- faithfulness                          : 답변이 검색된 context에 충실한가 (환각 여부)
- llm_context_precision_without_reference: 검색된 context가 질문에 관련 있나 (노이즈)
- answer_relevancy                      : 답변이 질문에 실제로 답했나 (임베딩 사용)

각 지표는 OpenAI를 채점관으로 호출하므로 **비용이 발생한다**. 그래서 평가셋의
질문마다 실제 `/api/chat` 파이프라인(triage → 검색 → rerank → 답변 생성)을 한 번
돌려 (question, retrieved_contexts, response)를 모은 뒤 RAGAS로 채점한다.

전제: `RAG_ENABLED=true` 와 `OPENAI_API_KEY` 가 설정돼 있어야 한다. 채점관 LLM은
`OPENAI_MODEL`(기본 gpt-4.1-mini)을 재사용하고, answer_relevancy용 임베딩 모델은
`RAGAS_EMBEDDING_MODEL`(기본 text-embedding-3-small)을 쓴다.

두 가지 방식으로 호출:

1. CLI 보고서:

   RAG_ENABLED=true OPENAI_API_KEY=... .venv/bin/python -m tests.eval.ragas_runner

2. pytest 회귀 가드(비용 발생, ragas 마크로만):

   RAG_ENABLED=true OPENAI_API_KEY=... .venv/bin/python -m pytest -m ragas

평가 질문은 retrieval 평가와 같은 tests/eval/retrieval_cases.yml 을 재사용한다
(must_include_titles 라벨은 무시하고 question/filters만 사용). 운영 데이터
(data/kau_notice_hub.db)가 있어야 검색이 동작한다.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import yaml

from app.chat_service import (
    _generate_with_openai,
    _retrieve_references,
    truncate,
)
from app.config import get_settings
from app.dependencies import _build_repository
from app.schemas import Notice
from app.service import NoticeQuery, NoticeService

CASES_PATH = Path(__file__).parent / "retrieval_cases.yml"

# build_context가 LLM에 넣는 본문 길이와 맞춰, 실제로 모델이 본 context를 채점한다.
CONTEXT_CHARS = 1400
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"

# RAGAS가 매기는 지표 컬럼명 (ragas 0.4.x 기준).
METRIC_NAMES = [
    "faithfulness",
    "llm_context_precision_without_reference",
    "answer_relevancy",
]


def _embedding_model() -> str:
    return os.environ.get("RAGAS_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)


def _load_cases() -> list[dict[str, Any]]:
    with CASES_PATH.open("r", encoding="utf-8") as f:
        cases = yaml.safe_load(f)
    if not isinstance(cases, list):
        raise RuntimeError("retrieval_cases.yml은 list여야 합니다.")
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

    한 공지 = 한 context chunk. 본문이 비면 요약/제목으로 폴백하고, 그래도 비면
    제외한다(빈 문자열 context는 채점을 망친다).
    """
    contexts: list[str] = []
    for notice in notices:
        text = notice.content or notice.summary or notice.title
        text = text.strip() if text else ""
        if text:
            contexts.append(truncate(text, CONTEXT_CHARS))
    return contexts


async def _collect_sample(
    service: NoticeService, case: dict[str, Any]
) -> dict[str, Any] | None:
    """케이스 하나를 실제 chat 파이프라인에 돌려 RAGAS 샘플 dict를 만든다.

    검색 분기(search)가 아니거나, 검색 0건이거나, 답변 생성이 실패하면 None을
    반환한다(채점 불가 케이스). 호출자가 사유를 로깅한다.
    """
    question = case["question"]
    filters = _filters_from_case(case)

    notices, _references, mode = await _retrieve_references(service, question, filters)
    if mode != "search" or not notices:
        return None

    contexts = _contexts_from_notices(notices)
    if not contexts:
        return None

    result = await _generate_with_openai(question, filters, notices)
    if result is None:
        return None
    answer, _model = result

    return {
        "case_id": case.get("id", question[:20]),
        "user_input": question,
        "retrieved_contexts": contexts,
        "response": answer,
    }


async def collect_samples() -> tuple[list[dict[str, Any]], list[str]]:
    """평가셋 전체를 파이프라인에 돌려 RAGAS 샘플 리스트와 스킵 사유를 모은다."""
    service = NoticeService(_build_repository())
    samples: list[dict[str, Any]] = []
    skipped: list[str] = []
    for case in _load_cases():
        sample = await _collect_sample(service, case)
        if sample is None:
            skipped.append(str(case.get("id", case.get("question", "?"))))
        else:
            samples.append(sample)
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


def run_ragas(samples: list[dict[str, Any]]) -> Any:
    """수집한 샘플을 RAGAS로 채점하고 EvaluationResult를 반환한다.

    ragas/langchain import는 함수 안에서 한다 — eval extra가 설치되지 않은
    환경(기본 CI)에서 이 모듈을 import만 해도 깨지지 않게 한다.
    """
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas import EvaluationDataset, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import (
        Faithfulness,
        LLMContextPrecisionWithoutReference,
        ResponseRelevancy,
    )

    settings = get_settings()
    api_key = settings.openai_api_key

    llm = LangchainLLMWrapper(
        ChatOpenAI(model=settings.openai_model, api_key=api_key, temperature=0)
    )
    embeddings = LangchainEmbeddingsWrapper(
        OpenAIEmbeddings(model=_embedding_model(), api_key=api_key)
    )

    metrics = [
        Faithfulness(llm=llm),
        LLMContextPrecisionWithoutReference(llm=llm),
        ResponseRelevancy(llm=llm, embeddings=embeddings),
    ]

    dataset = EvaluationDataset.from_list(samples)
    return evaluate(dataset, metrics=metrics, llm=llm, embeddings=embeddings)


def summarize(result: Any) -> dict[str, float]:
    """EvaluationResult에서 지표별 평균(NaN 제외)을 뽑는다."""
    df = result.to_pandas()
    summary: dict[str, float] = {}
    for name in METRIC_NAMES:
        if name in df.columns:
            summary[name] = float(df[name].mean(skipna=True))
    return summary


def format_report(result: Any, samples: list[dict[str, Any]], skipped: list[str]) -> str:
    df = result.to_pandas()
    metric_cols = [name for name in METRIC_NAMES if name in df.columns]

    short = {
        "faithfulness": "faith",
        "llm_context_precision_without_reference": "ctx_prec",
        "answer_relevancy": "ans_rel",
    }
    header = f"{'case':10s} " + " ".join(f"{short[c]:>9s}" for c in metric_cols)
    lines = [header, "-" * len(header)]
    for index, sample in enumerate(samples):
        row = df.iloc[index]
        cells = " ".join(f"{float(row[c]):9.3f}" for c in metric_cols)
        lines.append(f"{str(sample['case_id'])[:10]:10s} {cells}")

    summary = summarize(result)
    lines.append("-" * len(header))
    avg_cells = " ".join(f"{summary.get(c, float('nan')):9.3f}" for c in metric_cols)
    lines.append(f"{'AVG':10s} {avg_cells}")
    lines.append("")
    lines.append(f"채점 샘플 {len(samples)}건 / 스킵 {len(skipped)}건")
    if skipped:
        lines.append(f"스킵(검색 0건·도메인외·생성실패): {', '.join(skipped)}")
    return "\n".join(lines)


def main() -> None:
    _require_openai()
    samples, skipped = asyncio.run(collect_samples())
    if not samples:
        print("채점할 search 분기 샘플이 없습니다. 스킵:", ", ".join(skipped))
        return
    result = run_ragas(samples)
    print(format_report(result, samples, skipped))


if __name__ == "__main__":
    main()
