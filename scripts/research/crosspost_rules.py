"""교차 게시 판정 규칙.

후보: 게시판이 다르고 게시일 차이가 7일 이내이며, 괄호 머리말을 뗀 제목이 같거나 글자 2-gram 유사도가 0.8 이상인 쌍.

첨부파일 규칙: 두 공지의 첨부파일 이름이 모두 같고 개수도 같으면 하나로 합쳐도 되는 공지로 본다(2026-09-15 결정).
이름은 공백·대소문자를 무시해 비교한다. 학교 이미지 주소 끝부분(imageSrc.do)처럼 서로 다른 파일이 같은
이름으로 잡히는 경우는 파일명이 아니므로 비교하지 않는다. 비교할 첨부가 없으면 규칙을 적용하지 않는다.

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
BODY_AUTO_MERGE = 0.9

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


def attachment_name_list(post: dict[str, Any]) -> list[str]:
    names = []
    for attachment in post.get("attachments") or []:
        if not isinstance(attachment, dict):
            continue
        name = re.sub(r"\s+", "", str(attachment.get("name") or "")).lower()
        if name and not GENERIC_ATTACHMENT_NAME.match(name):
            names.append(name)
    return sorted(names)


def same_attachment_set(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """첨부파일 이름이 전부 같고 개수도 같으면 True. 비교할 첨부가 없으면 False."""
    names = attachment_name_list(a)
    return bool(names) and names == attachment_name_list(b)


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
