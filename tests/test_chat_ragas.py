"""RAGAS 기반 RAG 품질 회귀 가드.

OpenAI 채점 호출 비용이 들고 운영 데이터(data/kau_notice_hub.db)가 필요하므로
기본 pytest 실행에서는 제외된다(pyproject addopts: -m 'not ragas'). 명시적으로
실행한다:

    RAG_ENABLED=true OPENAI_API_KEY=... pytest -m ragas

ragas/langchain import와 무거운 의존성은 테스트 본문 안에서만 건드린다 —
pytest collection 단계에서 이 파일을 import해도(마크 제외와 무관하게 collection은
일어난다) eval extra가 없는 환경에서 깨지지 않게 한다.
"""

from __future__ import annotations

import asyncio

import pytest

from app.config import get_settings


@pytest.mark.ragas
def test_ragas_scores_are_well_formed() -> None:
    settings = get_settings()
    if not settings.rag_enabled or not settings.openai_api_key:
        pytest.skip("RAG_ENABLED=true 와 OPENAI_API_KEY 가 있어야 RAGAS 채점이 동작한다.")

    pytest.importorskip("ragas", reason="eval extra 미설치: pip install -e '.[eval]'")

    from tests.eval.ragas_runner import (
        METRIC_NAMES,
        collect_samples,
        dump_path,
        format_report,
        run_ragas,
        summarize,
        write_run_artifact,
    )

    samples, skipped = asyncio.run(collect_samples())
    assert samples, f"채점할 search 분기 샘플이 없습니다. 스킵: {skipped}"

    rows = run_ragas(samples)
    report = format_report(rows, skipped)
    print("\n" + report)

    # CLI(main)와 동일하게 질문·context·답변·점수를 아티팩트로 남겨 진단에 쓴다.
    artifact = dump_path()
    if artifact is not None:
        write_run_artifact(samples, rows, skipped, artifact)

    summary = summarize(rows)

    # 측정된 지표가 모두 나왔고 [0, 1] 범위인지 (NaN 아님) 확인.
    for name in METRIC_NAMES:
        assert name in summary, f"{name} 점수가 없습니다.\n{report}"
        score = summary[name]
        assert score == score, f"{name}=NaN (채점 실패).\n{report}"  # NaN != NaN
        assert 0.0 <= score <= 1.0, f"{name}={score} 가 [0,1] 밖.\n{report}"

    # baseline 측정 전이라 점수 하한 threshold는 아직 두지 않는다.
    # 첫 실행 결과를 보고 아래처럼 점진적으로 올린다(retrieval 가드와 동일 방식):
    #
    # assert summary["faithfulness"] >= 0.80, report
    # assert summary["context_precision_without_reference"] >= 0.70, report
    # assert summary["answer_relevancy"] >= 0.70, report
