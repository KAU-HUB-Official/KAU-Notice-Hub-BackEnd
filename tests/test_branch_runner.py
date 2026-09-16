"""branch_runner 로직 검증 — OpenAI 호출 없음.

triage LLM 을 질문별 고정 응답 stub 으로 바꿔 정상/오거부/오검색/legacy/근거없음을
일부러 만들고, 판정·혼동행렬·RAGAS 채점 가능 여부가 맞게 나오는지 본다.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import chat_service
from app.config import get_settings
from app.repository import NoticeSearchQuery, NoticeSearchResult
from app.schemas import Notice
from app.service import NoticeService
from app.service_pipeline import legacy_search
from tests.eval import branch_runner


class MemoryRepository:
    def __init__(self, notices: list[Notice]) -> None:
        self.notices = notices

    async def list_all(self) -> list[Notice]:
        return self.notices

    async def get_by_id(self, notice_id: str) -> Notice | None:
        return next((notice for notice in self.notices if notice.id == notice_id), None)

    async def search(self, query: NoticeSearchQuery) -> NoticeSearchResult:
        return legacy_search(self.notices, query)


def make_notice(notice_id: str, title: str, content: str = "본문") -> Notice:
    return Notice(
        id=notice_id,
        title=title,
        content=content,
        source="한국항공대학교 공식 홈페이지",
        sources=["한국항공대학교 공식 홈페이지"],
        category="학사",
        date="2026-04-20",
        tags=["학사"],
        attachments=[],
    )


# 질문 → triage LLM 이 돌려줄 원문. None 은 LLM 호출 실패(→ legacy 경로).
TRIAGE_REPLIES = {
    "수강신청 기간 알려줘": '{"mode":"search","keywords":["수강신청"]}',  # 정상 search
    "학생증 재발급 방법": '{"mode":"search","keywords":["학생증"]}',  # search 지만 근거 공지 없음
    "ㅁㄴㅇㄹ": '{"mode":"out_of_domain","keywords":[]}',  # 정상 거부
    "긱사 추가모집 해?": '{"mode":"out_of_domain","keywords":[]}',  # 오거부
    "ㅋㅋㅋ": '{"mode":"search","keywords":["ㅋㅋㅋ"]}',  # 오검색
    "장학금 언제": None,  # triage 실패
}


def _fake_llm(api_key, model, system_prompt, messages, **_kwargs):
    if "검색 분기" in system_prompt:  # TRIAGE_PROMPT 표식
        return TRIAGE_REPLIES[messages[-1]["content"]]
    return None  # rerank 는 호출되더라도 실패 → 상위 N개 폴백


def _case(case_id: str, question: str, expect: str) -> dict:
    return {
        "id": case_id,
        "question": question,
        "expect": expect,
        "filters": {},
        "decoded": None,
        "group": "t",
        "source": "t.yml",
    }


@pytest.fixture
def live_triage_env(monkeypatch):
    monkeypatch.setenv("RAG_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("RAG_QUERY_EXTRACTION_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_branch_verdicts_and_summary(live_triage_env) -> None:
    svc = NoticeService(
        MemoryRepository(
            [
                make_notice("n1", "2026학년도 2학기 수강신청 안내", content="수강신청 일정"),
                make_notice("n2", "장학금 신청 안내", content="장학금 신청"),
            ]
        )
    )
    cases = [
        _case("ok-search", "수강신청 기간 알려줘", "search"),
        _case("no-ground", "학생증 재발급 방법", "search"),
        _case("ok-reject", "ㅁㄴㅇㄹ", "out_of_domain"),
        _case("false-reject", "긱사 추가모집 해?", "search"),
        _case("false-search", "ㅋㅋㅋ", "out_of_domain"),
        _case("triage-fail", "장학금 언제", "search"),
    ]

    with patch.object(chat_service, "_call_openai_sync", side_effect=_fake_llm):
        results = await branch_runner.run_all(svc, cases)
    r = {x["id"]: x for x in results}

    assert (r["ok-search"]["actual"], r["ok-search"]["match"]) == ("search", True)
    assert r["ok-search"]["ragas_ready"] is True

    # 분기는 맞았지만 근거 공지가 없어 RAGAS 에선 스킵될 케이스
    assert (r["no-ground"]["actual"], r["no-ground"]["match"]) == ("search", True)
    assert r["no-ground"]["hits"] == 0
    assert r["no-ground"]["ragas_ready"] is False

    assert (r["ok-reject"]["actual"], r["ok-reject"]["match"]) == ("out_of_domain", True)
    assert (r["false-reject"]["actual"], r["false-reject"]["match"]) == ("out_of_domain", False)
    assert (r["false-search"]["actual"], r["false-search"]["match"]) == ("search", False)

    # triage 가 실패해도 반환값만 보면 search 로 보이고 최신 공지로 결과가 채워진다.
    # trace.mode 로 판정해야 legacy 로 잡히고, RAGAS 에서도 운영 경로 샘플이 아니므로 스킵된다.
    assert (r["triage-fail"]["actual"], r["triage-fail"]["match"]) == ("legacy", False)
    assert r["triage-fail"]["hits"] > 0
    assert r["triage-fail"]["ragas_ready"] is False

    s = branch_runner.summarize(results)
    assert s["matched"] == 3
    assert (s["false_reject"], s["false_search"], s["legacy"], s["errors"]) == (1, 1, 1, 0)
    assert s["confusion"] == {
        "search": {"search": 2, "out_of_domain": 1, "legacy": 1},
        "out_of_domain": {"out_of_domain": 1, "search": 1},
    }
    assert s["zero_hits"] == ["no-ground"]
    assert (s["search_expected"], s["ragas_ready"]) == (4, 1)

    report = branch_runner.format_report(results, s)
    assert "오거부" in report and "[false-reject] 기대 search → 실제 out_of_domain" in report


@pytest.mark.anyio
async def test_run_all_pins_today_to_snapshot_reference_date(monkeypatch) -> None:
    seen = []

    async def fake_retrieve(service, question, filters, *args, today=None, **kwargs):
        seen.append(today)
        trace = SimpleNamespace(
            mode="out_of_domain",
            triage_keywords=None,
            search_query=None,
            candidates=[],
            rerank_outcome=None,
            triage_raw=None,
            latency_ms={},
        )
        return [], [], "out_of_domain", trace

    monkeypatch.setattr(branch_runner, "_retrieve_references", fake_retrieve)

    await branch_runner.run_all(None, [_case("c", "ㅁㄴㅇㄹ", "out_of_domain")], date(2026, 9, 14))

    assert seen == [date(2026, 9, 14)]


def test_load_cases_accepts_group_dict_and_flat_list(tmp_path) -> None:
    grouped = tmp_path / "grouped.yml"
    grouped.write_text(
        "rag_quality:\n"
        "  - id: a\n    question: 수강신청 언제야\n"
        "negatives:\n"
        "  - id: b\n    question: ㅁㄴㅇㄹ\n    expect: out_of_domain\n",
        encoding="utf-8",
    )
    flat = tmp_path / "flat.yml"
    flat.write_text("- id: c\n  question: 장학금 알려줘\n", encoding="utf-8")

    cases = branch_runner.load_cases([grouped, flat])

    assert [(c["id"], c["expect"], c["group"]) for c in cases] == [
        ("a", "search", "rag_quality"),  # expect 생략 → search
        ("b", "out_of_domain", "negatives"),
        ("c", "search", "cases"),  # 평면 list
    ]


@pytest.mark.parametrize(
    "body, message",
    [
        ("- id: a\n  question: q\n  expect: legacy\n", "expect="),
        ("- id: a\n  question: q\n- id: a\n  question: q2\n", "id 중복"),
    ],
)
def test_load_cases_rejects_bad_input(tmp_path, body, message) -> None:
    path = tmp_path / "bad.yml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        branch_runner.load_cases([path])


def test_require_live_triage_blocks_when_rag_disabled(monkeypatch) -> None:
    monkeypatch.setenv("RAG_ENABLED", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit, match="RAG_ENABLED"):
            branch_runner._require_live_triage()
    finally:
        get_settings.cache_clear()
