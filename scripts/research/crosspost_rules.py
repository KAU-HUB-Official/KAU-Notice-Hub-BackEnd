"""교차 게시 판정 규칙.

첨부파일 규칙: 두 공지의 첨부파일 이름이 모두 같고 개수도 같으면 하나로 합쳐도 되는 공지로 본다(2026-09-15 결정).
이름은 공백·대소문자를 무시해 비교한다. 학교 이미지 주소 끝부분(imageSrc.do)처럼 서로 다른 파일이 같은
이름으로 잡히는 경우는 파일명이 아니므로 비교하지 않는다. 비교할 첨부가 없으면 규칙을 적용하지 않는다.
"""

from __future__ import annotations

import re
from typing import Any

GENERIC_ATTACHMENT_NAME = re.compile(
    r"^(imagesrc\.do|download\.do|filedown\.do|image|img|inline-image|첨부|첨부파일|파일|file)$"
)


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
