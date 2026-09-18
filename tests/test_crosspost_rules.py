"""scripts/research/crosspost_rules.py 첨부파일 규칙 검증."""

from __future__ import annotations

from scripts.research.crosspost_rules import (
    attachment_name_list,
    body_for_similarity,
    body_image_urls,
    body_similarity,
    different_attachment_files,
    loose_title,
    same_attachment_set,
    same_body_image_set,
    shared_attachment_names,
    similar_titles,
)


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


def test_number_prefix_extension_and_final_mark_are_the_same_file() -> None:
    a = _post("붙임2.중간강의평가응답방법(학생).pdf", "첨부1.공적조서양식.hwp")
    b = _post("중간강의평가응답방법(학생).pdf", "[첨부2]공적조서양식(최종).hwp")

    assert same_attachment_set(a, b)
    assert not different_attachment_files(a, b)
    assert same_attachment_set(_post("2026_boeing_day_참가팀_지원서.hwp"), _post("2026boeingday참가팀지원서.hwp"))


def test_same_document_in_two_formats_counts_once() -> None:
    both_formats = _post("모집공고.hwpx", "모집공고_.pdf")

    assert same_attachment_set(both_formats, _post("모집공고.pdf"))


def test_different_files_mean_different_notices_only_when_both_have_attachments() -> None:
    older = _post("강의시간표(20260306).pdf")
    newer = _post("(최종)강의시간표(20260414).xlsx")

    assert different_attachment_files(older, newer)  # 날짜가 다른 판은 다른 파일
    assert different_attachment_files(_post("서약서.hwp"), _post("서약서.hwp", "가이드라인.pdf"))  # 한쪽에 파일이 더 있음
    assert not different_attachment_files(_post("서약서.hwp"), {"attachments": []})  # 한쪽만 첨부
    assert not different_attachment_files(_post("imageSrc.do"), _post("신청서.hwp"))  # 파일명이 아닌 값은 비교하지 않음


def _images(*urls: str) -> dict:
    return {"content": "\n".join(f"![]({url})" for url in urls)}


HASHES = {
    "https://kau.ac.kr/a/poster.jpg": "h1",
    "https://college.kau.ac.kr/b/poster.jpg": "h1",
    "https://kau.ac.kr/a/detail.png": "h2",
    "https://college.kau.ac.kr/b/detail.png": "h2",
    "https://kau.ac.kr/c/other.png": "h3",
}


def test_body_images_equal_by_file_even_when_urls_differ() -> None:
    a = _images("https://kau.ac.kr/a/poster.jpg", "https://kau.ac.kr/a/detail.png")
    b = _images("https://college.kau.ac.kr/b/detail.png", "https://college.kau.ac.kr/b/poster.jpg")

    assert same_body_image_set(a, b, HASHES.get)


def test_body_images_one_shared_or_unknown_hash_is_not_enough() -> None:
    a = _images("https://kau.ac.kr/a/poster.jpg", "https://kau.ac.kr/a/detail.png")

    assert not same_body_image_set(a, _images("https://college.kau.ac.kr/b/poster.jpg"), HASHES.get)
    assert not same_body_image_set(
        a, _images("https://college.kau.ac.kr/b/poster.jpg", "https://kau.ac.kr/unknown.png"), HASHES.get
    )
    assert not same_body_image_set({"content": "본문"}, {"content": "본문"}, HASHES.get)


def test_site_chrome_images_are_ignored() -> None:
    a = _images("https://kau.ac.kr/a/poster.jpg", "https://kau.ac.kr/img/btn_list.gif")

    assert body_image_urls(a) == ["https://kau.ac.kr/a/poster.jpg"]
    assert same_body_image_set(a, _images("https://college.kau.ac.kr/b/poster.jpg"), HASHES.get)


def test_candidate_titles_and_body_similarity() -> None:
    assert similar_titles(loose_title("[학사] 2025-2 수강신청 안내"), loose_title("2025-2 수강신청 안내"))
    assert not similar_titles(loose_title("[공지] 휴강"), loose_title("휴강"))
    assert body_similarity(body_for_similarity("짧은 본문"), body_for_similarity("짧은 본문")) is None
