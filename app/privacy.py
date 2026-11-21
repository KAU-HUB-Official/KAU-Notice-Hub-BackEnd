"""공지에서 학번과 사람 이름을 가린다.

적용 대상은 세 곳이다. 사용자에게 렌더되는 공지 본문(`mask_notice_body()`),
검색 인덱스(`build_search_text()`), LLM 입력(`app/chat_service.py`)이다.

- **학번**: 형식이 정해진 10자리 숫자라 정규식으로 가린다.
- **이름**: 학생·교수·담당자 구분 없이 NER 모델로 가린다(`app/name_masking.py`).

전화번호, 이메일, 계좌번호는 문의처와 납부처라 사용자와 챗봇에게 꼭 필요해서
남긴다. 단, 메일 주소 자체가 학번(`2021○○○○14@kau.kr`)이면 학생을 특정하므로
학번 규칙대로 가린다. 메일이 없어도 공지 내용은 전달된다.

건드리지 않는 것이 있다.

- **제목**: 원문 URL이 없는 공지는 `build_notice_id()`가 제목으로 ID를 만든다.
  제목을 바꾸면 그 공지의 ID가 변해 사용자가 저장한 북마크가 끊긴다.
- **첨부파일**: 파일명과 URL을 그대로 둔다. PDF·HWP·이미지 안의 내용은 텍스트
  마스킹이 닿지 않으므로 그쪽 명단은 여전히 노출된다.

`PRIVACY_MASK_BODY=false`면 본문만 원문으로 돌아가고 검색 인덱스와 LLM 입력은
계속 가려진다. 공지 DB는 크롤링마다 통째로 교체되므로 설정을 바꾸고 다음 적재를
기다리면 된다.
"""

from __future__ import annotations

import re

# `*`는 마크다운 굵게(`**문의**`)를 깨뜨려 쓰지 않는다. `○`는 학교도 `박○영`처럼
# 이미 쓰는 글자다.
MASK_CHAR = "○"

# 10자리 학번. 앞뒤가 숫자나 하이픈, 점이면 제외해 전화번호와 파일명 날짜
# (`발표자 명단(20240614).pdf`)를 학번으로 오인하지 않는다.
STUDENT_ID_RE = re.compile(r"(?<![\d\-.])((?:19|20)\d{2}\d{6})(?![\d\-.])")

# 링크 주소. 이 안은 학번이든 이름이든 가리지 않는다. 주소 속 숫자를 가리면 링크와
# 이미지가 깨진다. 실제로 이미지 주소의 해시(`...db1928475806cbd0...`)에 든 10자리가
# 학번으로 잡혀 링크 2개가 깨진 적이 있다. 앞뒤 글자 조건만으로는 막을 수 없어서
# 주소 전체를 뺀다. 이름 마스킹(`app/name_masking.py`)도 같은 패턴을 쓴다.
URL_RE = re.compile(r"https?://\S+|\]\([^)]*\)|mailto:\S+")

STUDENT_ID_HEAD_CHARS = 4
STUDENT_ID_TAIL_CHARS = 2


def mask_student_ids(text: str) -> str:
    """10자리 학번의 가운데 4자리를 가린다. `2017999928` -> `2017○○○○28`.

    앞 4자리(입학년도)와 뒤 2자리는 남긴다. 학교도 `2025****40` 형태로 같은 관례를
    쓴다.

    안내문의 예시 학번(`2026123456`, `2011111111`)도 구분하지 않고 가린다. 숫자만
    보고는 예시인지 실제인지 확정할 수 없고, 실제 학번이 우연히 예시처럼 생겼으면
    그대로 노출된다.

    링크 주소(`URL_RE`) 안의 숫자는 학번처럼 생겨도 가리지 않는다. 단 학번으로 된 메일 주소는
    `mailto:` 링크 안이어도 가린다(메일 링크는 동작하지 않게 되지만 학생을 특정하지 않는 쪽을 택한다).
    """
    if not text:
        return text
    urls = [m.span() for m in URL_RE.finditer(text)]

    def replace(match: re.Match[str]) -> str:
        start, end = match.span(1)
        # 메일 주소의 앞부분이 학번이면 링크(`mailto:`, `](mailto:...)`) 안이어도 가린다.
        is_email = text.startswith("@", end)
        if not is_email and any(s < end and start < e for s, e in urls):
            return match.group(0)
        student_id = match.group(1)
        hidden = len(student_id) - STUDENT_ID_HEAD_CHARS - STUDENT_ID_TAIL_CHARS
        return (
            student_id[:STUDENT_ID_HEAD_CHARS]
            + MASK_CHAR * hidden
            + student_id[-STUDENT_ID_TAIL_CHARS:]
        )

    return STUDENT_ID_RE.sub(replace, text)


def _body_masking_enabled() -> bool:
    from app.config import get_settings

    return get_settings().privacy_mask_body


def mask_notice_body(markdown: str, *, enabled: bool | None = None) -> str:
    """공지 본문(사용자에게 렌더되는 마크다운)을 가린다.

    `normalize_notice()`에서 호출한다. 끄면(`PRIVACY_MASK_BODY=false`) 본문은
    원문 그대로 저장되고 검색 인덱스와 LLM 입력만 가려진다.
    """
    if not markdown:
        return markdown
    if enabled is None:
        enabled = _body_masking_enabled()
    if not enabled:
        return markdown
    return mask_personal_identifiers(markdown)


def mask_personal_identifiers(text: str) -> str:
    """마스킹 진입점. 본문, 검색 인덱스, LLM 입력이 모두 이 함수를 거친다.

    학번을 먼저 가린 뒤 이름을 가린다. 평가도 학번을 가린 본문으로 했다.
    """
    from app.name_masking import mask_names

    return mask_names(mask_student_ids(text))
