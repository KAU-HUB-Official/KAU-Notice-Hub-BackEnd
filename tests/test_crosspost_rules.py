"""scripts/research/crosspost_rules.py 첨부파일 규칙 검증."""

from __future__ import annotations

from scripts.research.crosspost_rules import attachment_name_list, same_attachment_set, shared_attachment_names


def _post(*names: str) -> dict:
    return {"attachments": [{"name": name, "url": f"https://kau.ac.kr/file/{i}"} for i, name in enumerate(names)]}


def test_all_names_and_count_equal_ignoring_spaces_and_case() -> None:
    a = _post("붙임2_가상여객단 신청양식.hwp", "붙임3_개인정보 동의서.HWP")
    b = _post("붙임3_개인정보동의서.hwp", "붙임2_가상여객단신청양식.hwp")

    assert same_attachment_set(a, b)


def test_one_shared_name_is_not_enough() -> None:
    a = _post("첨부2.연구계획서양식.hwp", "첨부1.제출안내.pdf")
    b = _post("첨부2.연구계획서양식.hwp")

    assert shared_attachment_names(a, b) == {"첨부2.연구계획서양식.hwp"}
    assert not same_attachment_set(a, b)


def test_duplicate_count_must_match() -> None:
    assert not same_attachment_set(_post("신청서.hwp", "신청서.hwp"), _post("신청서.hwp"))


def test_generic_url_endings_and_empty_lists_do_not_apply() -> None:
    assert attachment_name_list(_post("imageSrc.do", "첨부파일")) == []
    assert not same_attachment_set(_post("imageSrc.do"), _post("imagesrc.do"))
    assert not same_attachment_set({"attachments": []}, {"attachments": []})
