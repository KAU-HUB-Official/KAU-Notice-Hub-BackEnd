"""공지 검색 (retrieval) 품질 측정 runner.

두 가지 방식으로 호출:

1. CLI 보고서 (assertion 없이 표만 출력):

   .venv/bin/python -m tests.eval.runner

2. pytest 회귀 가드 (recall/MRR이 threshold 미만이면 fail):

   .venv/bin/python -m pytest -m eval

운영 데이터 (data/kau_notice_hub.db)를 사용하므로 DB 파일이 있어야 한다.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.dependencies import _build_repository
from app.repository import NoticeSearchQuery
from app.service import NoticeQuery, NoticeService

CASES_PATH = Path(__file__).parent / "retrieval_cases.yml"
DEFAULT_TOP_K = 10


@dataclass
class CaseResult:
    case_id: str
    question: str
    tags: list[str]
    retrieved_titles: list[str]
    must_titles: list[str]
    hits: list[bool] = field(default_factory=list)
    first_hit_rank: int | None = None

    @property
    def recall_at_5(self) -> float:
        if not self.must_titles:
            return 1.0
        hit_5 = sum(
            1 for t in self.must_titles if _matches(t, self.retrieved_titles[:5])
        )
        return hit_5 / len(self.must_titles)

    @property
    def recall_at_10(self) -> float:
        if not self.must_titles:
            return 1.0
        hit_10 = sum(
            1 for t in self.must_titles if _matches(t, self.retrieved_titles[:10])
        )
        return hit_10 / len(self.must_titles)

    @property
    def reciprocal_rank(self) -> float:
        return 1.0 / self.first_hit_rank if self.first_hit_rank else 0.0


def _matches(must_substring: str, retrieved_titles: list[str]) -> bool:
    needle = must_substring.strip()
    if not needle:
        return True
    return any(needle in title for title in retrieved_titles)


def _load_cases() -> list[dict[str, Any]]:
    with CASES_PATH.open("r", encoding="utf-8") as f:
        cases = yaml.safe_load(f)
    if not isinstance(cases, list):
        raise RuntimeError("retrieval_cases.yml은 list여야 합니다.")
    return cases


async def _run_one(service: NoticeService, case: dict[str, Any]) -> CaseResult:
    question = case["question"]
    filters = case.get("filters") or {}
    must = list(case.get("must_include_titles") or [])

    query = NoticeQuery(
        q=question,
        audience_group=filters.get("audience_group"),
        source_group=filters.get("source_group"),
        source=filters.get("source"),
        category=filters.get("category"),
        department=filters.get("department"),
        page=1,
        page_size=DEFAULT_TOP_K,
    )

    items = await service.find_relevant_notices(
        question,
        limit=DEFAULT_TOP_K,
        filters=query,
        fallback_to_latest=False,
    )
    titles = [n.title for n in items]

    first_hit_rank: int | None = None
    for index, title in enumerate(titles, start=1):
        if any(_matches(m, [title]) for m in must):
            first_hit_rank = index
            break

    return CaseResult(
        case_id=case["id"],
        question=question,
        tags=list(case.get("tags") or []),
        retrieved_titles=titles,
        must_titles=must,
        first_hit_rank=first_hit_rank,
    )


async def run_all() -> list[CaseResult]:
    cases = _load_cases()
    service = NoticeService(_build_repository())
    return [await _run_one(service, case) for case in cases]


def aggregate(results: list[CaseResult]) -> dict[str, float]:
    if not results:
        return {"recall@5": 0.0, "recall@10": 0.0, "mrr": 0.0, "n": 0}
    return {
        "recall@5": sum(r.recall_at_5 for r in results) / len(results),
        "recall@10": sum(r.recall_at_10 for r in results) / len(results),
        "mrr": sum(r.reciprocal_rank for r in results) / len(results),
        "n": len(results),
    }


def format_report(results: list[CaseResult]) -> str:
    lines: list[str] = []
    lines.append(
        f"{'id':6s} {'r@5':>5s} {'r@10':>5s} {'rank':>5s}  question"
    )
    lines.append("-" * 80)
    for r in results:
        rank = str(r.first_hit_rank) if r.first_hit_rank else "-"
        lines.append(
            f"{r.case_id:6s} {r.recall_at_5:5.2f} {r.recall_at_10:5.2f} "
            f"{rank:>5s}  {r.question}"
        )
    summary = aggregate(results)
    lines.append("-" * 80)
    lines.append(
        f"AVG    {summary['recall@5']:5.2f} {summary['recall@10']:5.2f} "
        f"mrr={summary['mrr']:.3f}  n={summary['n']}"
    )
    return "\n".join(lines)


def main() -> None:
    results = asyncio.run(run_all())
    print(format_report(results))
    print()
    failed = [r for r in results if r.recall_at_5 < 1.0]
    if failed:
        print(f"recall@5 < 1.0 케이스 ({len(failed)}건):")
        for r in failed:
            top = r.retrieved_titles[:3]
            print(
                f"  [{r.case_id}] q={r.question!r}  must={r.must_titles}"
                f"  top3={top}"
            )


if __name__ == "__main__":
    main()
