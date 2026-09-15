"""scripts/research/crosspost_rules.py 첨부파일 규칙 검증."""

from __future__ import annotations

from scripts.research.crosspost_rules import (
    attachment_name_list,
    body_for_similarity,
    body_image_urls,
    body_similarity,
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
