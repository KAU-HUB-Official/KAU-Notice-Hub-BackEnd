"""공지 적용 대상 라벨.

연구 세션이 사람 검수를 거쳐 확정한 라벨을 JSONL 파일(`NOTICE_LABELS_PATH`)로 받는다.
공지 DB는 크롤링마다 통째로 다시 만들어지므로 라벨은 DB 밖 파일에 두고, ingest 때마다
원문 URL로 맞춰 다시 붙인다. 라벨 파일 내용은 이 저장소에서 고치지 않는다.

대상 판정 규칙은 연구 코드(noticebench/audience.py의 `covers`)와 같아야 한다.
- 빈 audiences는 모든 학생이다.
- 신입생·편입생 사용자에게는 학부재학생 공지도 보인다. 단 excludes에 신입생·편입생이
  있으면(본문이 신입생을 분명히 뺀 공지) 보이지 않는다.
- 항공경영대학원생과 항공우주정책대학원생은 특수대학원생으로 묶는다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

from app.classification import normalize_filter_value

logger = logging.getLogger("app.notice_labels")

FRESHMEN = "신입생·편입생"

# 목록 target 값 → 그 target에 보이는 라벨 대상 코드
TARGET_AUDIENCE_CODES: dict[str, frozenset[str]] = {
    "학부재학생": frozenset({"학부재학생"}),
    FRESHMEN: frozenset({FRESHMEN, "학부재학생"}),
    "일반대학원생": frozenset({"일반대학원생"}),
    "특수대학원생": frozenset({"항공경영대학원생", "항공우주정책대학원생"}),
    "교직원·기타": frozenset({"교직원", "부속기관교육생", "외부"}),
}
TARGETS: tuple[str, ...] = tuple(TARGET_AUDIENCE_CODES)


@dataclass(frozen=True)
class NoticeLabel:
    audiences: tuple[str, ...]
    excludes: tuple[str, ...]
    series: str | None
    term: str | None
    label_version: str | None
    label_source: str | None


def normalize_target(value: str | None) -> str | None:
    """정의된 target이면 그 값을, 비었거나 모르는 값이면 None(필터 없음)을 돌려준다."""
    normalized = normalize_filter_value(value)
    return normalized if normalized in TARGET_AUDIENCE_CODES else None


def covers(audiences: Iterable[str], target: str, excludes: Iterable[str] = ()) -> bool:
    """대상 라벨(audiences, excludes)인 공지가 target 사용자에게 보이는가."""
    if target in set(excludes):
        return False
    audience_set = set(audiences)
    return not audience_set or bool(audience_set & TARGET_AUDIENCE_CODES[target])


def label_url_key(url: str | None) -> str | None:
    """라벨과 공지를 잇는 URL 키.

    스킴(http/https)은 버리고, 호스트는 소문자로 바꿔 `www.`를 떼고, 쿼리 인자는 정렬한다.
    """
    if not url or not url.strip():
        return None
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        return None
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[len("www.") :]
    if not netloc:
        return None
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return f"{netloc}{parsed.path}?{query}" if query else f"{netloc}{parsed.path}"


def load_notice_labels(path: str | Path, *, warn_missing: bool = True) -> dict[str, NoticeLabel]:
    """라벨 파일을 URL 키별로 읽는다. 파일이 없거나 줄이 깨져 있어도 예외 없이 경고만 남긴다.

    자동 라벨 파일처럼 처음에는 없는 게 정상인 파일은 warn_missing=False로 읽는다.
    """
    labels_file = Path(path).expanduser()
    try:
        lines = labels_file.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        if warn_missing:
            logger.warning("notice labels file not found: path=%s", labels_file)
        return {}
    except (OSError, UnicodeDecodeError):
        logger.warning("notice labels file is unreadable: path=%s", labels_file, exc_info=True)
        return {}

    labels: dict[str, NoticeLabel] = {}
    invalid = 0
    duplicated = 0
    for line in lines:
        if not line.strip():
            continue
        parsed = _parse_line(line)
        if parsed is None:
            invalid += 1
            continue
        key, label = parsed
        if key in labels:
            duplicated += 1
            continue
        labels[key] = label

    if invalid or duplicated:
        logger.warning(
            "notice labels skipped: path=%s invalid_lines=%s duplicated_urls=%s",
            labels_file,
            invalid,
            duplicated,
        )
    return labels


def _parse_line(line: str) -> tuple[str, NoticeLabel] | None:
    try:
        raw = json.loads(line)
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    key = label_url_key(raw.get("url") if isinstance(raw.get("url"), str) else None)
    audiences = _string_list(raw.get("audiences"))
    excludes = _string_list(raw.get("excludes", []))
    if key is None or audiences is None or excludes is None:
        return None
    return key, NoticeLabel(
        audiences=audiences,
        excludes=excludes,
        series=_optional_string(raw.get("series")),
        term=_optional_string(raw.get("term")),
        label_version=_optional_string(raw.get("label_version")),
        label_source=_optional_string(raw.get("label_source")),
    )


def _string_list(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return tuple(value)


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
