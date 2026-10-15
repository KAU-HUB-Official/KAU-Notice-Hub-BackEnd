"""라벨 없는 공지에 적용 대상 라벨을 자동으로 붙인다.

연구 세션의 확정 라벨(`NOTICE_LABELS_PATH`)은 정해진 시점의 공지만 덮으므로, 그 뒤에 수집된
공지는 여기서 라벨을 만든다. 순서는 연구 코드(noticebench/board_rules.py의 `decide`)와 같다.
1. 학과·특수대학원·부속기관·입찰·산학 게시판은 게시판 규칙으로 정한다.
2. 학교 전체 게시판이거나, 제목·본문에 다른 대상을 가리키는 말이 있으면 LLM이 정한다.
   LLM 기준은 연구 라벨 기준서 v5(specs/labels.md)의 대상 규칙이다.

결과는 `NOTICE_AUTO_LABELS_PATH`(JSONL)에 쌓는다. 공지 DB는 크롤링마다 다시 만들어지므로
DB 밖 파일에 두고, ingest가 연구 라벨 다음 순위로 붙인다. 대상만 정하고 시리즈·학기는 비운다.
LLM 호출이 실패한 공지는 기록하지 않아 다음 수집 때 다시 시도한다.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from app.notice_labels import FRESHMEN, label_url_key, load_notice_labels

logger = logging.getLogger("app.notice_auto_label")

AUTO_LABEL_VERSION = "auto-v5-2026-10-15"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENAI_TIMEOUT_SECONDS = 60
LLM_BODY_MAX_CHARS = 3000

AUDIENCE_CODES: tuple[str, ...] = (
    "학부재학생",
    FRESHMEN,
    "일반대학원생",
    "항공경영대학원생",
    "항공우주정책대학원생",
    "부속기관교육생",
    "교직원",
    "외부",
)
# 학부재학생에는 신입생이 포함되므로(기준서 v5 규칙 1) 이 넷이 모두 있으면 학생 전체다.
ALL_STUDENTS = frozenset({"학부재학생", "일반대학원생", "항공경영대학원생", "항공우주정책대학원생"})

# --- 게시판 규칙 (noticebench/board_rules.py와 같다) ---

FIXED = {"bid_notice": ("외부",), "research_notice": ("교직원",)}
INSTITUTE = {"amtc_notice", "life_notice", "atci_notice", "ftc_notice", "kasi_notice"}
SPECIAL = {"gradbus_notice": "항공경영대학원생", "college_gc91652_notice": "항공우주정책대학원생"}
DEPT_GRAD = {"materials_grad_notice": "일반대학원생"}
# 대상이 공지마다 달라 LLM이 보는 학교 전체 게시판. 새 게시판을 추가하면 여기와 위 집합 중
# 어디에 속하는지 정한다. 어디에도 없으면 학과 게시판으로 보고 학부재학생 규칙을 쓴다.
SCHOOL = {
    "general_notice", "academic_notice", "scholarship_notice", "grad_notice", "job_notice",
    "college_gc63585_notice", "event_notice", "human_rights_notice", "covid_notice", "dorm_notice",
    "it_notice", "museum_notice", "admission_notice", "library_notice", "ctl_notice", "lms_notice",
}

_DEPT_TITLE = re.compile(
    r"대학원|석사|박사|신입생|새내기|신\s*[·•ㆍ.]?\s*편입|편입생|입학|채용|교직원|교원|교수|연수|누구나|일반인|외부|시민"
)
_DEPT_BODY = re.compile(r"대학원생|누구나|일반인|외부인|전\s*학생|모든\s*학생|교직원")
_SPECIAL_TITLE = re.compile(r"모집|채용|연수|교수|교직원|최고위")
EXCLUDES_SERIES = {"수강신청 일정 안내", "수강지도상담 안내", "등록 일정 안내"}
_EXCLUDES = re.compile(
    r"(신\s*·?\s*편입학\s*예정\s*학생|신\s*·\s*편입생|신입생\s*및\s*편입생)"
    r"[^\n]{0,50}?(별도|진행\s*예정|대상\s*아님|제외)"
)

# --- 시리즈 이름 (noticebench/series.py와 같다). excludes 규칙이 시리즈를 보므로 옮겨 둔다 ---

_BRACKETS = re.compile(r"\[[^\]]*\]|\([^)]*\)|<[^>]*>|【[^】]*】|〈[^〉]*〉|「[^」]*」")
_TIME = re.compile(
    r"\d{2,4}\s*학년도|\d{2,4}\s*년도|\d{2,4}\s*년|\d{2,4}\s*[-.]\s*[12]\s*학기|제?\s*[12]\s*학기"
    r"|하계|동계|제?\s*\d+\s*(?:회|기|차)"
)
_EDIT_MARKS = re.compile(
    r"(?<![\w가-힣])(?:update|수정|재공지|재안내|재게시|필독|중요)(?![\w가-힣])", re.IGNORECASE
)
# (표준 이름, 키에 맞출 정규식, 제외 정규식). 위에서부터 처음 맞는 규칙을 쓴다.
_SERIES_RULES: list[tuple[str, str, str | None]] = [
    ("계절학기 학점교류 안내", r"계절\s*학기 학점교류", None),
    ("학점교류 수강 안내", r"학점교류 수강\s*안내", None),
    ("학점교류 신청 안내", r"학점교류", None),
    ("학과 수강인원 증원 안내", r"수강인원 증원|증원\s*계획|수강제한인원 초과", None),
    ("학과 수강신청 유의사항", r"수강신청 관련 안내|수강신청 유의사항", r"개별연구|종합설계|캡스톤|변경기간|장학배정"),
    ("수강신청 일정 안내", r"^(신 편입생 )?수강\s*신청 (및 강의\s*시간표 |일정 )?안내$", None),
    ("등록 일정 안내", r"등록\s*기간|등록\s*방법", None),
    ("등록금 분할납부 안내", r"분할\s*징수|분할\s*납부", None),
    ("미등록·미복학·미수강자 안내", r"미등록|미복학|미수강", None),
    ("창업휴학 신청 안내", r"창업\s*휴학", None),
    ("휴·복학 신청 안내", r"휴학|복학", r"수강|교과과정|권장"),
    ("재입학 신청 안내", r"재입학", None),
    ("계절학기 폐강 교과목 안내", r"계절\s*학기.*폐강", None),
    ("계절학기 성적 확인 안내", r"계절\s*학기.*성적", None),
    ("계절학기 수요조사 안내", r"계절\s*(?:학기|수업).*수요조사", None),
    ("계절학기 개설과목 안내", r"계절\s*학기.*개설\s*과목", None),
    ("계절학기 실시 안내", r"계절\s*학기 실시", None),
    ("폐강 교과목 안내", r"폐강", None),
    ("성적 확인 안내", r"^성적 확인 안내$", None),
    ("성적경고자 상담 안내", r"성적경고자", None),
    ("강의평가 실시 안내", r"강의\s*평가", None),
    ("기말시험 안내", r"기말\s*시험", r"학점은행제"),
    ("보강기간 안내", r"보강\s*기간", None),
    ("수강지도상담 안내", r"수강\s*지도\s*상담", None),
    ("국가장학금 신청 안내", r"국가장학금 신청", r"가구원|소속대학|이벤트|멤버십"),
    ("국가근로장학 신청 안내", r"국가근로.*신청", None),
    ("국가근로장학생 선발 안내", r"국가근로.*(?:선발|명단)", None),
    ("교내장학금 신청 안내", r"교내장학금 신청", None),
    ("지자체 학자금 대출이자 지원 안내", r"학자금\s*대출\s*이자|대출\s*이자\s*지원", None),
    ("학자금 대출 안내", r"학자금\s*대출", r"신용회복|장학"),
    ("생활관생 모집 안내", r"생활관생.*모집", None),
    ("학위수여식 안내", r"학위수여식", None),
    ("조기졸업 신청 안내", r"조기졸업", None),
    ("졸업인증 안내", r"졸업인증", None),
    ("복수전공·부전공 이수확인서 제출 안내", r"(?:복수전공|(?<!세)부전공).*이수\s*확인서", None),
    ("복수전공·부전공 신청 안내", r"(?:복수전공|(?<!세)부전공).*(?:신청|공고|변경|취소)", None),
    ("융합전공 이수확인서 제출 안내", r"융합전공.*이수\s*확인서", None),
    ("융합전공 신청 안내", r"융합전공.*(?:신청|모집)", None),
    ("대학원 지도교수·전공 변경 안내", r"지도교수\s*(?:및\s*전공\s*변경|배정|변경)|대학원\s*전과|대학원.*전공\s*변경", None),
    ("전공배정·변경 신청 안내", r"전공\s*배정|주전공 배정|전공\s*변경", None),
    ("학위청구논문 예비발표 안내", r"청구논문 예비발표", None),
    ("학위청구논문 본심사 안내", r"청구논문 본(?:심사|발표)", None),
    ("학위논문 완성본 제출 안내", r"학위논문 완성본", None),
    ("연구계획서 제출 안내", r"연구계획서 제출", None),
    ("연구지도보고서 제출 안내", r"연구지도\s*보고서", None),
    ("대학원 영어시험 안내", r"영어\s*시험", None),
    ("대학원 종합시험 안내", r"종합\s*시험", None),
    ("학생증 발급 안내", r"학생증", None),
    ("신입생 학번 안내", r"(?:신\s*입생|신입학생|편입생).*학번|학번\s*(?:부여|조회|확인)", None),
    ("예비군 안내", r"예비군", None),
    ("현장실습학기제 오리엔테이션 안내", r"현장실습학기제.*오리엔테이션", None),
    ("현장실습학기제 안내", r"현장실습학기제", None),
    ("사무실 운영시간·휴무 안내", r"사무실|행정실|근무\s*시간|단축\s*근무", r"프로그램|강의|상담|식당|라운지|이전"),
    ("K-MOOC 안내", r"K\s*MOOC", None),
    ("사물함 신청 안내", r"사물함", None),
    ("개별연구 결과보고서 제출 안내", r"개별연구.*보고서", None),
    ("개별연구 수강신청 안내", r"개별연구", None),
    ("초과학기 신청 안내", r"초과\s*학기", None),
    ("학기재수 신청 안내", r"학기\s*재수", None),
    ("사이버강좌 수강 안내", r"사이버\s*강좌", None),
]
_COMPILED_SERIES = [
    (name, re.compile(pattern), re.compile(exclude) if exclude else None)
    for name, pattern, exclude in _SERIES_RULES
]

_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+")


def series_key(title: str) -> str:
    text = unicodedata.normalize("NFKC", title)
    text = _BRACKETS.sub(" ", text)
    text = _TIME.sub(" ", text)
    text = _EDIT_MARKS.sub(" ", text)
    text = re.sub(r"\d+", " ", text)
    text = re.sub(r"[^\w가-힣]+", " ", text).replace("_", " ")
    return " ".join(text.split())


def canonical_series(key: str) -> str:
    for name, pattern, exclude in _COMPILED_SERIES:
        if pattern.search(key) and not (exclude and exclude.search(key)):
            return name
    return key


def clean_markdown(text: str) -> str:
    """이미지 문법과 주소를 지우고 링크는 글자만 남긴다."""
    text = _IMAGE.sub(" ", text)
    text = _LINK.sub(r"\1", text)
    return _URL.sub(" ", text)


@dataclass(frozen=True)
class Decision:
    by: str  # "rule" | "llm"
    audiences: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()
    reason: str = ""


def decide(board: str | None, title: str, body: str) -> Decision:
    if not board:
        return Decision("llm", reason="게시판 키 없음")
    if board in FIXED.keys() | INSTITUTE and "채용" in title:
        return Decision("rule", ("외부",), reason="산학협력단·부속기관 채용 공고")
    if board in FIXED:
        return Decision("rule", FIXED[board], reason="게시판 규칙")
    if board in INSTITUTE:
        return Decision("rule", ("부속기관교육생",), reason="부속기관 게시판")
    if board in SCHOOL:
        return Decision("llm", reason="학교 전체 게시판")
    if board in SPECIAL:
        if _SPECIAL_TITLE.search(title):
            return Decision("llm", reason="특수대학원 게시판, 제목에 모집·채용·연수 등")
        return Decision("rule", (SPECIAL[board],), reason="특수대학원 게시판")
    cleaned = clean_markdown(body)
    if _DEPT_TITLE.search(title):
        return Decision("llm", reason="학과 게시판, 제목에 다른 대상을 가리키는 말")
    if _DEPT_BODY.search(cleaned):
        return Decision("llm", reason="학과 게시판, 본문에 다른 대상을 가리키는 말")
    if board in DEPT_GRAD:
        return Decision("rule", (DEPT_GRAD[board],), reason="학과 대학원 게시판")
    excludes: tuple[str, ...] = ()
    if canonical_series(series_key(title)) in EXCLUDES_SERIES and _EXCLUDES.search(cleaned):
        excludes = (FRESHMEN,)
    return Decision("rule", ("학부재학생",), excludes, reason="학과 게시판")


# --- LLM ---

LLM_INSTRUCTIONS = f"""한국항공대학교 공지 한 건의 적용 대상을 정한다. 대상 코드는 아래 8개다.
- 학부재학생: 학부 재학생. 복학 예정자를 포함하고, "재학생"에는 신입생도 포함된다.
- {FRESHMEN}: 학부 신입생·편입생에게만 해당하는 공지에만 붙인다.
- 일반대학원생: 일반대학원 석·박사.
- 항공경영대학원생: 항공·경영대학원(특수대학원).
- 항공우주정책대학원생: 항공우주정책대학원(특수대학원).
- 부속기관교육생: 항공기술교육원·평생교육원·항공교통관제교육원·비행교육원·항공안전교육원 등 부속기관 교육생.
- 교직원: 교수·직원. 연구원·연구지원인력·조교 등 대학 소속 인력도 교직원이다.
- 외부: 업체·입찰자·채용 지원자 등 학생도 교직원도 아닌 사람. 채용 공고는 외부다.

규칙
1. 제목이나 게시판이 아니라 본문의 적용 대상으로 정한다. 공지의 주된 내용이 적용되는 대상만 넣고, 곁가지 문장에 나온 대상은 넣지 않는다. 다른 대상의 일정을 예고만 한 경우(예: "신·편입생은 별도 공지")도 넣지 않는다.
2. 주된 내용이 여러 대상에 적용되면 모두 넣는다.
3. 학생 전체(학부·대학원, 신입생 포함. 예: "대학(원)생", "학생 누구나", "전 학생")는 빈 목록이다. 학교 밖 사람도 참여할 수 있는 공개 행사·공모전도 빈 목록이다.
4. 학사 절차(수강, 등록, 휴·복학, 성적 등)가 아닌 학교 공지(행사, 특강, 프로그램, 장학)의 "본교 재학생", "학생 누구나"는 빈 목록이다. "재학생"만 적힌 학사 절차 공지는 학부재학생이다.
5. "학생", "학생들"처럼 구분 없는 표현은 학교 전체 게시판이면 빈 목록, 학과·학부 게시판이면 학부재학생이다.
6. 본문이 "대학원(생)"이라고만 하면: 한 대학원의 자체 절차(학위논문, 종합시험, 연구계획서, 그 대학원의 수강신청·등록 등)를 그 대학원 게시판에 올린 공지는 그 대학원 하나다. 학교 전체 제도·행사(학자금 대출, 생활관, 예비군, 학생증, 연구윤리 교육 등)는 대학원 셋 모두다. 대학원생이 대상인지, 어느 대학원인지 애매하면 넓힌다. 본문 문의처에 나오는 대학원은 대상에 넣는다. 단 특수대학원 게시판의 "재학생"과 자체 절차(등록, 휴·복학)는 그 대학원이다.
7. 하위 집단(졸업예정자, 휴학생, 특정 학년)은 속한 학생 유형으로 붙인다. 학석사연계과정생은 학부재학생과 일반대학원생이다.
8. 모두 대상인 학교 공지를 학과 게시판에 옮긴 사본은 학부재학생으로 좁힌다. 원문이 특정 대상이면 사본도 그 대상이다.
9. 본문에 대상 표현이 전혀 없으면 게시판 기본값을 쓴다. 단 내용으로 정해지면 그쪽을 따른다(교환학생 → 학부재학생, 수상 소식처럼 대상이 없는 글 → 빈 목록).
   게시판 기본값: 대학원·신소재공학과 대학원 → 일반대학원생 / 경영대학원 → 항공경영대학원생 / 항공우주정책대학원 → 항공우주정책대학원생 / 부속기관 → 부속기관교육생 / 학사공지·장학공지·학과·학부·전공·단과대학 게시판·새내기성공센터·부트캠프사업단·드림칼리지디자인 → 학부재학생 / 그 밖(일반공지, 행사, 취업, 국제교류처, 생활관, 인권센터, 학술정보관, 입학처, 교수학습센터 등) → 빈 목록.

자주 틀리는 경우
- 빈 목록은 "모든 사용자"(학생과 교직원 모두)다. 학생 코드를 모두 나열하거나 여러 코드를 늘어놓지 말고 빈 목록으로 쓴다. 시설 운영·휴무 안내처럼 학교 구성원 전체가 보는 공지도 빈 목록이다.
- "대학원(생)"은 일반대학원생 하나가 아니다. 어느 대학원인지 정해지지 않았으면 일반대학원생·항공경영대학원생·항공우주정책대학원생 셋을 모두 넣는다.
- "학부 및 대학원 (재학생/재적생)", "학부생 및 대학원생"은 학생 전체이므로 빈 목록이다(생활관 모집, 폭력예방교육 등).
- 학교 학위수여식 안내는 빈 목록이다. 대학원 게시판의 학위수여식 안내는 대학원 셋이다. 강의평가 안내는 학부재학생과 대학원 셋이다.
- 채용 공고(학교·산학협력단이 사람을 뽑는 공고)는 외부다. 기업 채용설명회·상담회처럼 학생이 참여하는 취업 행사는 빈 목록이다.
- 학교 전체 게시판의 행사·특강·교육·프로그램이 "재학생", "본교생"을 대상으로 하면 빈 목록이다(인권센터 교육, 대회 등). 학부재학생으로 좁히지 않는다.
- 장학생 선발(외부 재단·지자체 장학 포함), 교환학생·해외 프로그램, 비교과 프로그램은 본문이 대학원생을 함께 말하지 않으면 학부재학생이다.

excludes: 학부재학생 공지인데 본문이 신·편입생을 분명히 뺄 때만(예: "신·편입학 예정 학생은 2/24~25 별도 진행", "새로 입학하는 신·편입생은 대상 아님") ["{FRESHMEN}"]이다. 그 밖에는 빈 목록이다."""

LLM_SCHEMA = {
    "type": "json_schema",
    "name": "notice_audience",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["audiences", "excludes", "reason"],
        "properties": {
            "audiences": {
                "type": "array",
                "items": {"type": "string", "enum": list(AUDIENCE_CODES)},
                "description": "적용 대상 코드. 학생 전체·모두면 빈 목록",
            },
            "excludes": {
                "type": "array",
                "items": {"type": "string", "enum": [FRESHMEN]},
            },
            "reason": {"type": "string", "description": "판단 근거 한 문장"},
        },
    },
}


@dataclass(frozen=True)
class NoticeForLabel:
    url: str
    board: str | None
    board_name: str | None
    title: str
    body: str
    date: str | None
    attachment_names: tuple[str, ...]


def build_llm_input(notice: NoticeForLabel) -> str:
    body = clean_markdown(notice.body).strip()
    if len(body) > LLM_BODY_MAX_CHARS:
        body = body[:LLM_BODY_MAX_CHARS] + "\n(본문 잘림)"
    board = " ".join(part for part in (notice.board_name, f"({notice.board})" if notice.board else None) if part)
    lines = [
        f"게시판: {board or '알 수 없음'}",
        f"게시일: {notice.date or '알 수 없음'}",
        f"제목: {notice.title}",
    ]
    if notice.attachment_names:
        lines.append("첨부: " + ", ".join(notice.attachment_names))
    lines.append("본문:")
    lines.append(body or "(본문 없음)")
    return "\n".join(lines)


def normalize_audiences(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """정해진 순서로 중복 없이 정리한다.

    학부재학생과 대학원 셋이 모두 있으면 빈 목록(모두)으로 쓴다. 기준서 v5는 둘 다 허용하고
    (강의평가: "학부재학생 + 대학원 셋 또는 빈 목록"), 사람 검수 라벨과 맞춰 보면 빈 목록 쪽이 더 맞았다.
    """
    present = {value for value in values if value in AUDIENCE_CODES}
    if ALL_STUDENTS <= present:
        return ()
    return tuple(code for code in AUDIENCE_CODES if code in present)


def label_with_llm(
    notice: NoticeForLabel, *, api_key: str, model: str
) -> tuple[tuple[str, ...], tuple[str, ...], str] | None:
    """(audiences, excludes, reason). 호출이나 응답이 잘못되면 None."""
    payload = {
        "model": model,
        "store": False,
        "temperature": 0,
        "max_output_tokens": 300,
        "instructions": LLM_INSTRUCTIONS,
        "input": [
            {"role": "user", "content": [{"type": "input_text", "text": build_llm_input(notice)}]}
        ],
        "text": {"format": LLM_SCHEMA},
    }
    try:
        response = requests.post(
            OPENAI_RESPONSES_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=OPENAI_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.warning("notice auto label request failed: %s", type(exc).__name__)
        return None
    if response.status_code >= 400:
        logger.warning("notice auto label response status %s", response.status_code)
        return None
    try:
        data = response.json()
        text = "".join(
            part.get("text", "")
            for item in data.get("output", [])
            for part in item.get("content", []) or []
            if part.get("type") == "output_text"
        )
        parsed = json.loads(text)
    except (ValueError, AttributeError, TypeError):
        logger.warning("notice auto label response was not valid JSON")
        return None
    audiences = parsed.get("audiences") if isinstance(parsed, dict) else None
    excludes = parsed.get("excludes") if isinstance(parsed, dict) else None
    if not isinstance(audiences, list) or not isinstance(excludes, list):
        logger.warning("notice auto label response has no audiences/excludes")
        return None
    reason = parsed.get("reason") if isinstance(parsed.get("reason"), str) else ""
    # 연구 규칙과 같이 신입생 제외는 수강신청·수강지도상담·등록 공지에만 둔다. LLM은 휴·복학처럼
    # 신입생 언급만 있는 공지에도 붙이는 경우가 많았다(사람 검수 라벨 대비).
    clean_excludes = (
        (FRESHMEN,)
        if FRESHMEN in excludes and canonical_series(series_key(notice.title)) in EXCLUDES_SERIES
        else ()
    )
    return normalize_audiences(audiences), clean_excludes, reason


# --- 실행 ---


@dataclass(frozen=True)
class AutoLabelResult:
    candidates: int  # 연구 라벨·자동 라벨 모두 없는 공지
    rule_labeled: int
    llm_labeled: int
    llm_failed: int
    llm_skipped: int  # 호출 한도나 API 키가 없어 이번에 미룬 공지


def notices_from_snapshot(json_path: str | Path) -> list[NoticeForLabel]:
    raw = json.loads(Path(json_path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("공지 JSON 파일은 배열(Array) 형식이어야 합니다.")
    notices: list[NoticeForLabel] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = _first_string(item, ("original_url", "url", "link", "href"))
        if not url:
            continue
        notices.append(
            NoticeForLabel(
                url=url,
                board=_first_string(item, ("board_key",)),
                board_name=_first_source_name(item.get("source_name") or item.get("source")),
                title=_first_string(item, ("title", "subject", "name")) or "",
                body=_first_string(item, ("content", "body", "text", "description")) or "",
                date=_first_string(item, ("published_at", "date")),
                attachment_names=_attachment_names(item.get("attachments")),
            )
        )
    return notices


def label_unlabeled_notices(
    *,
    json_path: str | Path,
    labels_path: str | Path,
    auto_labels_path: str | Path,
    api_key: str | None,
    model: str,
    max_llm_calls: int,
) -> AutoLabelResult:
    """연구 라벨과 자동 라벨이 모두 없는 공지에 라벨을 붙여 auto_labels_path에 더한다."""
    auto_file = Path(auto_labels_path).expanduser()
    known = set(load_notice_labels(labels_path))
    known |= set(load_notice_labels(auto_file, warn_missing=False))

    new_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    candidates = rule_labeled = llm_labeled = llm_failed = llm_skipped = 0
    llm_calls = 0
    labeled_at = datetime.now().astimezone().isoformat(timespec="seconds")

    for notice in notices_from_snapshot(json_path):
        key = label_url_key(notice.url)
        if key is None or key in known or key in seen:
            continue
        seen.add(key)
        candidates += 1

        decision = decide(notice.board, notice.title, notice.body)
        if decision.by == "rule":
            new_rows.append(
                _row(notice.url, decision.audiences, decision.excludes, "auto_rule", decision.reason, labeled_at)
            )
            rule_labeled += 1
            continue

        if not api_key or llm_calls >= max_llm_calls:
            llm_skipped += 1
            continue
        llm_calls += 1
        result = label_with_llm(notice, api_key=api_key, model=model)
        if result is None:
            llm_failed += 1
            continue
        audiences, excludes, reason = result
        new_rows.append(
            _row(notice.url, audiences, excludes, "auto_llm", reason, labeled_at, model=model)
        )
        llm_labeled += 1

    if new_rows:
        _append_atomically(auto_file, new_rows)

    result = AutoLabelResult(candidates, rule_labeled, llm_labeled, llm_failed, llm_skipped)
    logger.info(
        "notice auto labels: candidates=%s rule=%s llm=%s llm_failed=%s llm_skipped=%s path=%s",
        result.candidates,
        result.rule_labeled,
        result.llm_labeled,
        result.llm_failed,
        result.llm_skipped,
        auto_file,
    )
    return result


def _row(
    url: str,
    audiences: tuple[str, ...],
    excludes: tuple[str, ...],
    source: str,
    reason: str,
    labeled_at: str,
    *,
    model: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "url": url,
        "audiences": list(audiences),
        "excludes": list(excludes),
        "series": None,
        "term": None,
        "departments": [],
        "label_version": AUTO_LABEL_VERSION,
        "label_source": source,
        "reason": reason,
        "labeled_at": labeled_at,
    }
    if model:
        row["model"] = model
    return row


def _append_atomically(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    added = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.tmp.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tmp.write(existing + added)
        os.replace(tmp_name, path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _first_string(item: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_source_name(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
    return None


def _attachment_names(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    names: list[str] = []
    for item in value:
        name = item.get("name") if isinstance(item, dict) else None
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return tuple(names)
