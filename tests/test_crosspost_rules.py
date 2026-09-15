"""scripts/research/crosspost_rules.py 첨부파일명 규칙 검증."""

from __future__ import annotations

from scripts.research.crosspost_rules import attachment_names, shared_attachment_names


def _post(*names: str) -> dict:
    return {"attachments": [{"name": name, "url": f"https://kau.ac.kr/file/{i}"} for i, name in enumerate(names)]}


def test_same_attachment_name_ignoring_spaces_and_case() -> None:
    a = _post("2024학년도 예비군훈련계획.pdf", "안내문.HWP")
    b = _post("2024학년도예비군훈련계획.PDF")

    assert shared_attachment_names(a, b) == {"2024학년도예비군훈련계획.pdf"}


def test_generic_url_endings_are_not_file_names() -> None:
    a = _post("imageSrc.do", "첨부파일")
    b = _post("imagesrc.do", "첨부파일")

    assert attachment_names(a) == set()
    assert shared_attachment_names(a, b) == set()


def test_no_attachments_share_nothing() -> None:
    assert shared_attachment_names({"attachments": []}, _post("신청서.hwp")) == set()
