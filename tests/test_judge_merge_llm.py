"""scripts/research/judge_merge_llm.py 합치기·최종 판정 규칙 (API 호출 없음)."""

from __future__ import annotations

from scripts.research.judge_merge_llm import final_judgment, merged_body


def test_merged_body_keeps_base_and_appends_additions_under_header() -> None:
    merged = merged_body("기준 본문", ["항공MRO전공 문의 02-300-0000", "  "])

    assert merged == "기준 본문\n\n[추가 안내]\n- 항공MRO전공 문의 02-300-0000"
    assert merged_body("기준 본문", []) == "기준 본문"


def test_merge_survives_only_with_base_and_nothing_missing() -> None:
    assert final_judgment("merge", "A", []) == "merge"
    assert final_judgment("merge", "B", ["수강 신청 기간"]) == "keep_both"  # 검사에서 빠진 정보가 나옴
    assert final_judgment("merge", "none", []) == "keep_both"  # 기준 본문을 못 고름
    assert final_judgment("merge", "A", None) == "keep_both"  # 검사를 못 함
    assert final_judgment("keep_both", "none", None) == "keep_both"
    assert final_judgment(None, None, None) is None  # 판정 호출 실패
