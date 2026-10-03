"""공지에서 개인 식별자와 연락처를 가리는 순수 함수 모음.

적용 대상은 세 곳이다. 사용자에게 렌더되는 공지 본문(`mask_notice_body()`),
검색 인덱스(`build_search_text()`), LLM 입력(`app/chat_service.py`)이다.

건드리지 않는 것이 있다.

- **제목**: `build_notice_id()`가 제목으로 공지 ID를 만든다. 제목을 바꾸면 ID가
  변해 사용자가 저장한 북마크가 끊긴다. 본문은 ID 계산에 쓰이지 않아 안전하다.
- **첨부파일**: 파일명과 URL을 그대로 둔다. PDF·HWP·이미지 안의 내용은 텍스트
  마스킹이 닿지 않으므로 그쪽 명단은 여전히 노출된다.

공지 7,857건(2016-11 ~ 2026-09) 전수 스캔 결과는 이렇다.

- 주민등록번호와 생년월일: 0건
- 실제 학번: 32건. 안내문의 예시 학번(`2026123456`)은 대상이 아니다
- 표의 성명/이름 컬럼: 322건
- 전화번호, 이메일, 계좌번호: 4,700여 건. 사실상 전부 부서 업무 연락처와
  학교 법인계좌다

연락처는 개인정보가 아닌 쪽이 대부분이지만 기본값은 가리는 쪽으로 둔다. 되돌릴
때는 설정에서 끈다. `PRIVACY_MASK_BODY=false`면 본문만 원문으로 돌아가고,
`PRIVACY_MASK_CONTACTS=false`면 학번과 표 성명 셀만 가린다. 공지 DB는 크롤링마다
통째로 교체되므로 설정을 바꾸고 다음 적재를 기다리면 된다.
"""

from __future__ import annotations

import re

# --- 학번 -------------------------------------------------------------------

# 10자리 학번. 앞뒤가 숫자나 하이픈, 점이면 제외해 전화번호와 파일명 날짜
# (`발표자 명단(20240614).pdf`)를 학번으로 오인하지 않는다.
STUDENT_ID_RE = re.compile(r"(?<![\d\-.])((?:19|20)\d{2}\d{6})(?![\d\-.])")

STUDENT_ID_YEAR_CHARS = 4
MASK_CHAR = "○"

EXAMPLE_SEQUENTIAL_TAILS = frozenset(
    {"123456", "234567", "345678", "456789", "654321", "987654"}
)

# --- 이름 -------------------------------------------------------------------

# 표 헤더에서 찾는 사람 이름 컬럼 라벨.
NAME_COLUMN_LABELS = ("성명", "이름", "학생명")

# 셀 하나가 한글 이름 하나로만 이루어진 경우에만 가린다.
KOREAN_NAME_RE = re.compile(r"^[가-힣]{2,4}$")

# `| --- | --- |` 구분 행. 상위 헤더를 추적할 때 건너뛴다.
SEPARATOR_CELL_RE = re.compile(r":?-{3,}:?")

MASKED_STUDENT_ID_PATTERN = r"(?:19|20)\d{2}" + MASK_CHAR + r"{6}"

# 가려진 학번 바로 뒤에 붙은 한글 이름. normalize_notice()가 비정형 표를 평문으로
# 펼치면 파이프가 사라져 컬럼 위치를 쓸 수 없는데(학번·실명 195명이 실린 캡스톤
# 공지가 그 경우다), 학번과 이름이 나란히 남는 배치는 그대로라 이 앵커는 살아남는다.
NAME_AFTER_ID_RE = re.compile(
    r"(" + MASKED_STUDENT_ID_PATTERN + r")([ \t]+)([가-힣]{2,4})(?![가-힣])"
)

# --- 연락처 -----------------------------------------------------------------

# 주민등록번호. 전수 스캔 0건이지만 유입 대비로 둔다.
RRN_RE = re.compile(r"(?<!\d)\d{6}\s*-\s*[1-4]\d{6}(?!\d)")

# 이메일. 로컬 파트만 가리고 도메인은 남긴다.
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})")

# 전화번호. 0으로 시작하는 지역번호·휴대폰과 1588 형태를 함께 잡는다. 공지 날짜
# (`2024.11.6.`, `2026-09-15`)는 2로 시작해 걸리지 않는다.
#
# 첫 구분자는 필수다. 생략을 허용하면 URL 안의 긴 해시
# (`?physical=ec8ba6e57d182021049940a24eb87c7b07c19`)를 전화번호로 보고 잘라
# 링크를 깨뜨린다(전수 기준 80개). 구분자 없는 9~11자리 숫자열 44건을 확인했는데
# 전부 URL 해시와 파일명이고 실제 전화번호는 없었다.
#
# lookaround는 숫자와 하이픈만 배제한다. 마스킹 문자를 넣으면 공지가 쓰는 마크다운
# 굵게(`**대학일자리플러스센터 02-300-0027**`)에 가려 번호 13건이 빠져나갔다.
# 멱등성은 마스킹 문자가 숫자가 아니라는 점으로 이미 보장된다.
PHONE_RE = re.compile(
    r"(?<![\d\-])(0\d{1,2}|1\d{3})([-.\s])(\d{3,4})([-.\s]?)\d{4}(?![\d\-])"
)

# 계좌번호. 은행·계좌·입금·예금주 앵커가 앞 40자 안에 있을 때만 본다.
ACCOUNT_ANCHOR = r"(?:계좌|입금|예금주|은행)"
ACCOUNT_RE = re.compile(
    r"(" + ACCOUNT_ANCHOR + r"[^\n]{0,40}?)(\d{2,6}-\d{2,6}-\d{2,8})"
)

# 가려진 주소가 남은 mailto 링크. normalize_content_markdown()이 이메일을
# `[addr](mailto:addr)` 형태로 유지하는데, 주소를 가리고 링크만 남기면 클릭 시
# 깨진 주소로 메일 앱이 열린다. 평문으로 펼쳐 둔다.
MASKED_MAILTO_RE = re.compile(
    r"\[(" + MASK_CHAR * 3 + r"@[^\]\n]+)\]\(mailto:[^)\n]*\)"
)


def _is_example_student_id(student_id: str) -> bool:
    """안내문이 예시로 적어둔 학번인지 판정한다.

    실제 데이터에서 학번 패턴 75건 중 43건이 예시값이었다(`2026123456`,
    `2011111111`, `2019222222`). 더미 필터가 없으면 오탐이 절반을 넘는다.

    판정은 좁게 둔다. 뒤 6자리가 한 숫자로만 채워졌거나 연속 숫자인 경우만
    예시로 본다. `숫자 종류가 둘 이하`처럼 넓게 잡으면 `2018121111`(뒤 6자리
    `121111`) 같은 실제 학번을 예시로 오판해 그대로 노출된다. 예시값을 몇 개 더
    가리는 손해는 검색어 하나가 덜 걸리는 정도지만, 실제 학번을 놓치면 사람이
    특정된다.
    """
    tail = student_id[STUDENT_ID_YEAR_CHARS:]
    if len(set(tail)) == 1:
        return True
    return tail in EXAMPLE_SEQUENTIAL_TAILS


def mask_student_ids(text: str) -> str:
    """10자리 학번의 뒤 6자리를 가린다. `2017121128` -> `2017○○○○○○`.

    입학년도 4자리는 남긴다. 공지 맥락에서 몇 학번인지는 의미가 있고, 학교도
    `2025****40` 형태로 이미 같은 관례를 쓰고 있다.
    """
    if not text:
        return text

    def replace(match: re.Match[str]) -> str:
        student_id = match.group(1)
        if _is_example_student_id(student_id):
            return student_id
        head = student_id[:STUDENT_ID_YEAR_CHARS]
        return head + MASK_CHAR * (len(student_id) - STUDENT_ID_YEAR_CHARS)

    return STUDENT_ID_RE.sub(replace, text)


def _mask_korean_name(name: str) -> str:
    return name[0] + MASK_CHAR * (len(name) - 1)


def mask_names_adjacent_to_student_ids(text: str) -> str:
    """가려진 학번에 바로 붙은 한글 이름을 가린다.

    `mask_student_ids()` 다음에 호출해야 한다. 학번을 먼저 `2017○○○○○○`로 바꿔
    두면 그 토큰이 이름의 앵커가 되어, 표가 평문으로 펼쳐진 공지에서도
    `2017○○○○○○ 심재원`의 이름을 찾을 수 있다.

    학번 바로 뒤만 본다. 학번 앞은 `기계 2018○○○○○○ 이휘`처럼 소속명이 오는
    자리여서, 그쪽까지 보면 학과명을 이름으로 오탐한다. 같은 줄의 담당교수처럼
    학번이 딸리지 않은 이름도 업무 정보로 보고 건드리지 않는다.

    남는 한계: 표가 평문으로 펼쳐지고 이름이 학번보다 앞에 오는 배치는 가리지
    못한다. 관측된 데이터에서 그 배치는 학교가 이미 `조O빈`으로 가려 둔
    공지들이었다.
    """
    if not text or MASK_CHAR not in text:
        return text

    def replace(match: re.Match[str]) -> str:
        return match.group(1) + match.group(2) + _mask_korean_name(match.group(3))

    return NAME_AFTER_ID_RE.sub(replace, text)


def _split_table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _find_name_columns(cells: list[str]) -> set[int]:
    found: set[int] = set()
    for index, cell in enumerate(cells):
        compact = cell.replace(" ", "")
        if any(label in compact for label in NAME_COLUMN_LABELS):
            found.add(index)
    return found


def _is_separator_row(cells: list[str]) -> bool:
    filled = [cell for cell in cells if cell]
    if not filled:
        return False
    return all(SEPARATOR_CELL_RE.fullmatch(cell) for cell in filled)


def _merged_span(cells: list[str]) -> tuple[int, int] | None:
    """헤더 행의 병합 구간을 `(시작 컬럼, 너비)`로 돌려준다.

    HTML colspan이 마크다운으로 바뀌면 병합된 칸이 빈 셀로 남는다.
    `| NO | 활동구분 | 팀명 | 팀장 | | | 비고 |`에서 팀장 뒤의 빈 셀 둘이 그
    흔적이고, 그 구간이 하위 헤더 행이 설명하는 컬럼 범위다.
    """
    for index, cell in enumerate(cells):
        if not cell:
            continue
        end = index + 1
        while end < len(cells) and not cells[end]:
            end += 1
        width = end - index
        if width > 1:
            return index, width
    return None


def _align_name_columns(
    found: set[int],
    cells: list[str],
    parent_cells: list[str] | None,
) -> set[int]:
    """하위 헤더에서 찾은 컬럼 번호를 상위 헤더의 병합 구간에 맞춘다.

    `| 학부(과) | 학번 | 성명 |`처럼 표 너비보다 짧은 헤더 행은 자기 안에서는
    성명이 2번 컬럼이지만 데이터 행에서는 5번 컬럼이다. 보정하지 않으면 엉뚱한
    셀을 보게 되어 아무것도 가리지 못한다.
    """
    if parent_cells is None or len(cells) >= len(parent_cells):
        return found
    span = _merged_span(parent_cells)
    if span is None or span[1] != len(cells):
        return found
    offset = span[0]
    return {index + offset for index in found}


def mask_name_columns(markdown: str) -> str:
    """마크다운 표에서 성명/이름 컬럼에 해당하는 셀만 가린다.

    헤더를 첫 행에서만 찾지 않고 표의 모든 행에서 찾는다. 실제 공지에는 헤더가
    두 행으로 쪼개진 표가 있고, 그 경우 컬럼 번호를 병합 구간에 맞춰 보정한다.
    """
    if not markdown or "|" not in markdown:
        return markdown

    lines = markdown.split("\n")
    name_columns: set[int] = set()
    parent_cells: list[str] | None = None
    masked_lines: list[str] = []

    for line in lines:
        if not line.lstrip().startswith("|"):
            # 표가 끝나면 다음 표로 컬럼 위치가 새어나가지 않도록 비운다.
            name_columns = set()
            parent_cells = None
            masked_lines.append(line)
            continue

        cells = _split_table_cells(line)
        header_columns = _find_name_columns(cells)
        if header_columns:
            name_columns |= _align_name_columns(header_columns, cells, parent_cells)
            masked_lines.append(line)
            continue

        if not _is_separator_row(cells):
            parent_cells = cells

        if not name_columns:
            masked_lines.append(line)
            continue

        changed = False
        for index in name_columns:
            if index >= len(cells):
                continue
            cell = cells[index]
            if KOREAN_NAME_RE.match(cell):
                cells[index] = _mask_korean_name(cell)
                changed = True

        if changed:
            indent = line[: len(line) - len(line.lstrip())]
            masked_lines.append(indent + "| " + " | ".join(cells) + " |")
        else:
            masked_lines.append(line)

    return "\n".join(masked_lines)


def mask_resident_registration_numbers(text: str) -> str:
    """주민등록번호를 가린다. 전수 스캔 0건이지만 유입 대비용이다."""
    return RRN_RE.sub(MASK_CHAR * 6 + "-" + MASK_CHAR * 7, text)


def mask_emails(text: str) -> str:
    """이메일의 로컬 파트만 가린다. `cap@kau.ac.kr` -> `○○○@kau.ac.kr`.

    도메인은 개인정보가 아니고, 남겨 두면 어느 기관 메일인지는 읽을 수 있다.
    """
    return EMAIL_RE.sub(lambda match: MASK_CHAR * 3 + "@" + match.group(1), text)


def mask_phone_numbers(text: str) -> str:
    """전화번호의 뒷자리를 가린다. `02-300-0272` -> `02-○○○-○○○○`.

    국번과 가입자번호만 가리고 지역번호나 통신사 접두는 남긴다. 공지 날짜는 2로
    시작해 패턴에 걸리지 않는다.
    """

    def replace(match: re.Match[str]) -> str:
        prefix, first_sep, middle, second_sep = match.groups()
        return prefix + first_sep + MASK_CHAR * len(middle) + second_sep + MASK_CHAR * 4

    return PHONE_RE.sub(replace, text)


def mask_account_numbers(text: str) -> str:
    """계좌번호를 가린다. 은행·계좌·입금 같은 앵커가 앞에 있을 때만 본다.

    앵커 없이 세 묶음 숫자 패턴으로 잡으면 전화번호를 계좌로 오인한다. 전수
    스캔에서 그 패턴이 공지 40%를 잡았고 대부분 전화번호였다.
    `mask_phone_numbers()` 다음에 호출해 남은 숫자 묶음만 처리한다.
    """

    def replace(match: re.Match[str]) -> str:
        return match.group(1) + re.sub(r"\d", MASK_CHAR, match.group(2))

    return ACCOUNT_RE.sub(replace, text)


def mask_contacts(text: str) -> str:
    """주민번호, 이메일, 전화번호, 계좌번호를 가린다.

    호출 순서가 중요하다. 전화번호를 먼저 가려 두면 계좌 패턴이 전화번호를 다시
    집어가지 않는다.
    """
    if not text:
        return text
    masked = mask_resident_registration_numbers(text)
    masked = mask_emails(masked)
    masked = mask_phone_numbers(masked)
    return mask_account_numbers(masked)


def _contacts_enabled() -> bool:
    from app.config import get_settings

    return get_settings().privacy_mask_contacts


def _body_masking_enabled() -> bool:
    from app.config import get_settings

    return get_settings().privacy_mask_body


def mask_notice_body(markdown: str, *, enabled: bool | None = None) -> str:
    """공지 본문(사용자에게 렌더되는 마크다운)을 가린다.

    `normalize_notice()`에서 호출한다. 끄면(`PRIVACY_MASK_BODY=false`) 본문은
    원문 그대로 저장되고 검색 인덱스와 LLM 입력만 가려진다.

    제목은 건드리지 않는다. `build_notice_id()`가 제목으로 공지 ID를 만들기
    때문에, 제목을 바꾸면 ID가 바뀌어 사용자가 저장한 북마크가 끊긴다. 본문은
    ID 계산에 쓰이지 않아 안전하다.

    첨부파일과 이미지도 건드리지 않는다. 첨부 파일명은 그대로 두고, PDF·HWP·
    이미지 안의 내용은 텍스트 마스킹이 닿지 않는다.

    되돌리기는 쉽다. 공지 DB는 크롤링마다 통째로 교체되므로 설정을 바꾸고 다음
    적재를 기다리면 원문 스냅샷에서 다시 만들어진다.
    """
    if not markdown:
        return markdown
    if enabled is None:
        enabled = _body_masking_enabled()
    if not enabled:
        return markdown
    masked = mask_personal_identifiers(markdown)
    return MASKED_MAILTO_RE.sub(lambda match: match.group(1), masked)


def mask_personal_identifiers(text: str, *, include_contacts: bool | None = None) -> str:
    """검색 인덱스와 LLM 입력의 진입점.

    학번과 표 성명 셀은 항상 가린다. 연락처는 `include_contacts`로 끌 수 있고,
    생략하면 설정(`PRIVACY_MASK_CONTACTS`, 기본 켜짐)을 따른다.

    멱등이다. `2017○○○○○○`는 10자리 숫자가 아니라 다시 매치되지 않고, 학교가
    이미 가린 `박○영`이나 `김*진`도 한글 이름 패턴에 걸리지 않으며, 이미 가린
    `02-○○○-○○○○`도 전화번호 패턴에 다시 걸리지 않는다.
    """
    masked = mask_student_ids(text)
    masked = mask_names_adjacent_to_student_ids(masked)
    masked = mask_name_columns(masked)
    if include_contacts is None:
        include_contacts = _contacts_enabled()
    if include_contacts:
        masked = mask_contacts(masked)
    return masked
