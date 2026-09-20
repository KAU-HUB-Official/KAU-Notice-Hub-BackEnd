"""scripts/research/judge_merge_llm.py 합치기·최종 판정 규칙 (API 호출 없음)."""

from __future__ import annotations

from scripts.research.judge_merge_llm import SCHEMA, final_judgment, fixed_base, judge_input, judge_schema, merged_body


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


def _post(*names: str) -> dict:
    return {"attachments": [{"name": n} for n in names]}


def test_base_is_fixed_to_the_side_with_attachments() -> None:
    assert fixed_base(_post("신청서.hwp"), _post()) == "A"
    assert fixed_base(_post(), _post("신청서.hwp")) == "B"
    assert fixed_base(_post("imageSrc.do"), _post("신청서.hwp")) == "B"  # 파일명이 아닌 값은 첨부로 치지 않음
    assert fixed_base(_post(), _post()) is None
    assert fixed_base(_post("a.hwp"), _post("b.hwp")) is None  # 둘 다 첨부면 규칙 단계에서 이미 정해짐


def test_fixed_base_limits_the_answer_and_is_stated_in_input() -> None:
    assert judge_schema("B")["schema"]["properties"]["base"]["enum"] == ["B", "none"]
    assert judge_schema(None) is SCHEMA
    assert SCHEMA["schema"]["properties"]["base"]["enum"] == ["A", "B", "none"]  # 원본 스키마는 그대로
    assert judge_input("본문A", "본문B", "B").startswith("기준 본문: B\n\n[공지 A 본문]")
    assert judge_input("본문A", "본문B", None).startswith("[공지 A 본문]")
