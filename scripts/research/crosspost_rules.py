"""교차 게시 판정 규칙.

후보: 게시판이 다르고 게시일 차이가 7일 이내이며, 괄호 머리말을 뗀 제목이 같거나 글자 2-gram 유사도가 0.8 이상인 쌍.

첨부파일 규칙 (2026-09-15, 2026-09-19 결정)
- 두 공지의 첨부파일이 모두 같고 개수도 같으면 하나로 합쳐도 되는 공지로 본다.
- 두 공지 모두 첨부가 있는데 파일이 다르면 다른 공지로 본다. 같은 시리즈라도 첨부가 다르면 주로 제공하는
  정보가 다르기 때문이다. 한쪽에만 첨부가 있으면 이 규칙을 적용하지 않는다(파일을 안 붙이고 옮긴 경우가 많다).
- 같은 파일인지는 이름으로 본다. 공백·대소문자, 앞 번호(첨부1., 붙임2., [첨부1]), 확장자, 끝 표기((최종), (1), _),
  이름 안의 기호(_ - . · 괄호)는 무시한다. 한 공지에 같은 문서가 형식만 달리 올라온 경우(공고.pdf, 공고.hwpx)는 한 파일로 센다.
- 학교 이미지 주소 끝부분(imageSrc.do)처럼 서로 다른 파일이 같은 이름으로 잡히는 경우는 파일명이 아니므로
  비교하지 않는다. 비교할 첨부가 없으면 규칙을 적용하지 않는다.

본문 같음 규칙 (2026-09-19 결정): 정규화한 본문 글자가 정확히 같고(50자 이상) 본문 이미지도 같으면(둘 다 없거나
파일이 전부 같음) 하나로 합쳐도 되는 공지로 본다. 비슷한 정도(유사도)로는 판정하지 않는다. 재게시와 대상별 변형
공지를 유사도로는 가를 수 없어서다. 글이 같아도 포스터만 다를 수 있으므로 한쪽에만 이미지가 있으면 적용하지 않는다.

본문 이미지 규칙: 두 공지의 본문 이미지 파일(내용 해시)이 모두 같고 개수도 같으면 하나로 합쳐도 되는 공지로 본다
(2026-09-15 결정). 게시판마다 같은 포스터를 새로 올려 주소가 달라지므로 주소가 아니라 파일 내용으로 비교한다.
해시를 모르는 이미지가 하나라도 있거나 본문 이미지가 없으면 규칙을 적용하지 않는다.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

CANDIDATE_WINDOW_DAYS = 7
MIN_TITLE_LENGTH = 6
TITLE_SIMILARITY = 0.8
MIN_BODY_LENGTH = 50

GENERIC_ATTACHMENT_NAME = re.compile(
    r"^(imagesrc\.do|download\.do|filedown\.do|image|img|inline-image|첨부|첨부파일|파일|file)$"
)
MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\((\S+?)(?:\s+\"[^\"]*\")?\)")
SITE_CHROME_IMAGE = re.compile(r"/(btn_|icon_|logo|tit_logo|bullet|blank\.gif)", re.I)


def loose_title(title: str) -> str:
    title = re.sub(r"[\[\(【<〈「][^\]\)】>〉」]{0,20}[\]\)】>〉」]", "", title or "")
    return re.sub(r"[^0-9a-z가-힣]", "", title.lower())


def bigram_jaccard(a: str, b: str) -> float:
    ga = {a[i : i + 2] for i in range(max(1, len(a) - 1))}
    gb = {b[i : i + 2] for i in range(max(1, len(b) - 1))}
    return len(ga & gb) / len(ga | gb) if ga | gb else 1.0


def similar_titles(a: str, b: str) -> bool:
    """loose_title을 거친 두 제목이 후보 조건을 만족하면 True."""
    if min(len(a), len(b)) < MIN_TITLE_LENGTH:
        return False
    return a == b or bigram_jaccard(a, b) >= TITLE_SIMILARITY


def body_for_similarity(content: str) -> str:
    content = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", content or "")
    content = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", content)
    content = re.sub(r"https?://\S+|\S+\.(jpg|jpeg|png|gif)\S*", " ", content, flags=re.I)
    content = re.sub(r"\*\*\[(이미지 본문|동영상 본문|첨부파일 공지)\]\*\*.*", "", content, flags=re.S)
    content = re.sub(r"[#*|>`_\-=~]+", " ", content)
    return re.sub(r"\s+", "", content).lower()


def body_similarity(a: str, b: str) -> float | None:
    """body_for_similarity를 거친 두 본문의 글자 3-gram Jaccard. 한쪽이라도 50자 미만이면 None(비교 불가)."""
    if min(len(a), len(b)) < MIN_BODY_LENGTH:
        return None
    ga = {a[i : i + 3] for i in range(max(1, len(a) - 2))}
    gb = {b[i : i + 3] for i in range(max(1, len(b) - 2))}
    return len(ga & gb) / len(ga | gb) if ga | gb else 1.0


def same_body_text(a: str, b: str) -> bool:
    """body_for_similarity를 거친 두 본문이 정확히 같고 50자 이상이면 True."""
    return len(a) >= MIN_BODY_LENGTH and a == b


def same_or_no_body_images(
    a: dict[str, Any], b: dict[str, Any], sha256_of: Callable[[str], str | None]
) -> bool:
    """두 공지 모두 본문 이미지가 없거나, 둘 다 있고 파일이 전부 같으면 True."""
    if not body_image_urls(a) and not body_image_urls(b):
        return True
    return same_body_image_set(a, b, sha256_of)


def attachment_name_list(post: dict[str, Any]) -> list[str]:
    names = []
    for attachment in post.get("attachments") or []:
        if not isinstance(attachment, dict):
            continue
        name = re.sub(r"\s+", "", str(attachment.get("name") or "")).lower()
        if name and not GENERIC_ATTACHMENT_NAME.match(name):
            names.append(name)
    return sorted(names)


ATTACHMENT_EXTENSION = re.compile(r"\.(hwp|hwpx|pdf|docx?|xlsx?|pptx?|jpe?g|png|gif|zip)$")
ATTACHMENT_NUMBER_PREFIX = re.compile(r"^(\[?(첨부|붙임)\d*\]?[.)_\-]?|\(?\d{1,2}\)?[.)_\-])")
ATTACHMENT_MARK_SUFFIX = re.compile(r"(\(최종\)|_최종|\(\d\)|_+)+$")


def attachment_core_name(name: str) -> tuple[str, str]:
    """(표기를 걷어낸 이름, 확장자). name 은 attachment_name_list 가 정규화한 이름."""
    ext_match = ATTACHMENT_EXTENSION.search(name)
    ext = ext_match.group(1) if ext_match else ""
    core = ATTACHMENT_EXTENSION.sub("", name)
    core = ATTACHMENT_NUMBER_PREFIX.sub("", core)
    core = re.sub(r"^\(최종\)", "", core)
    core = ATTACHMENT_MARK_SUFFIX.sub("", core)
    core = re.sub(r"[^0-9a-z가-힣]", "", core)
    return core, ext


def attachment_files(post: dict[str, Any]) -> list[str]:
    """비교용 파일 목록(정렬). 같은 문서가 형식만 달리 여러 개면 하나로, 같은 이름이 두 번이면 두 개로 센다."""
    exts_by_core: dict[str, list[str]] = {}
    for name in attachment_name_list(post):
        core, ext = attachment_core_name(name)
        exts_by_core.setdefault(core, []).append(ext)
    files = []
    for core, exts in exts_by_core.items():
        files.extend([core] * max(exts.count(e) for e in set(exts)))
    return sorted(files)


def same_attachment_set(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """첨부파일이 전부 같고 개수도 같으면 True. 비교할 첨부가 없으면 False."""
    files = attachment_files(a)
    return bool(files) and files == attachment_files(b)


def different_attachment_files(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """두 공지 모두 첨부가 있는데 파일이 다르면 True. 한쪽이라도 첨부가 없으면 False."""
    files_a, files_b = attachment_files(a), attachment_files(b)
    return bool(files_a) and bool(files_b) and files_a != files_b


def shared_attachment_names(a: dict[str, Any], b: dict[str, Any]) -> set[str]:
    return set(attachment_name_list(a)) & set(attachment_name_list(b))


def body_image_urls(post: dict[str, Any]) -> list[str]:
    """본문 이미지 주소(사이트 버튼·로고 제외, 중복 주소 하나로). 본문 마크다운에 없으면 크롤러가 모은 본문 이미지를 쓴다."""
    urls = [u for u in MARKDOWN_IMAGE.findall(post.get("content") or "") if not SITE_CHROME_IMAGE.search(u)]
    if not urls:
        urls = [
            str(asset.get("url"))
            for asset in post.get("content_assets") or []
            if isinstance(asset, dict)
            and asset.get("type") == "inline_image"
            and asset.get("url")
            and not SITE_CHROME_IMAGE.search(str(asset.get("url")))
        ]
    return [u for u in dict.fromkeys(urls) if u.startswith(("http://", "https://"))]


def same_body_image_set(
    a: dict[str, Any], b: dict[str, Any], sha256_of: Callable[[str], str | None]
) -> bool:
    """본문 이미지 파일 내용이 전부 같고 개수도 같으면 True. 이미지가 없거나 해시를 모르는 이미지가 있으면 False."""
    hashes = []
    for post in (a, b):
        urls = body_image_urls(post)
        values = [sha256_of(u) for u in urls]
        if not urls or not all(values):
            return False
        hashes.append(sorted(values))
    return hashes[0] == hashes[1]
