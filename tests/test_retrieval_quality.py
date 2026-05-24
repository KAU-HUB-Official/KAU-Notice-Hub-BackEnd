"""pytest -m eval 회귀 가드.

운영 데이터 (data/kau_notice_hub.db)가 필요. CI 기본 실행에서는 제외.
threshold는 Phase 1 fix 적용 후 측정값을 기준으로 점진적으로 올린다.
"""

from __future__ import annotations

import asyncio

import pytest

from tests.eval.runner import aggregate, format_report, run_all


@pytest.mark.eval
def test_retrieval_quality_meets_thresholds() -> None:
    results = asyncio.run(run_all())
    summary = aggregate(results)

    report = format_report(results)
    print("\n" + report)

    # Phase 1 fix 적용 후 threshold. baseline 측정 결과를 보고 갱신.
    assert summary["recall@5"] >= 0.70, (
        f"recall@5={summary['recall@5']:.2f} < 0.70\n{report}"
    )
    assert summary["recall@10"] >= 0.85, (
        f"recall@10={summary['recall@10']:.2f} < 0.85\n{report}"
    )
    assert summary["mrr"] >= 0.55, (
        f"mrr={summary['mrr']:.2f} < 0.55\n{report}"
    )
