"""교차 게시 판정 규칙.

첨부파일명 규칙: 두 공지에 이름이 같은 첨부파일이 있으면 같은 공지로 본다(2026-09-15 결정).
이름은 공백·대소문자를 무시해 비교한다. 학교 이미지 주소 끝부분(imageSrc.do)처럼 서로 다른 파일이
같은 이름으로 잡히는 경우는 파일명이 아니므로 비교하지 않는다.
주의: 공용 서식(예: 전공변경신청서.hwp)을 대상이 다른 공지들이 함께 첨부하는 경우에도 같은 공지로 판정된다.
"""

from __future__ import annotations

import re
from typing import Any

GENERIC_ATTACHMENT_NAME = re.compile(
    r"^(imagesrc\.do|download\.do|filedown\.do|image|img|inline-image|첨부|첨부파일|파일|file)$"
)


def attachment_names(post: dict[str, Any]) -> set[str]:
    names = set()
    for attachment in post.get("attachments") or []:
        if not isinstance(attachment, dict):
            continue
        name = re.sub(r"\s+", "", str(attachment.get("name") or "")).lower()
        if name and not GENERIC_ATTACHMENT_NAME.match(name):
            names.add(name)
    return names


def shared_attachment_names(a: dict[str, Any], b: dict[str, Any]) -> set[str]:
    return attachment_names(a) & attachment_names(b)
