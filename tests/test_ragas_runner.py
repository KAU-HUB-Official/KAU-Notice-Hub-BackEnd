"""ragas_runner 샘플 수집·집계 로직 검증 — OpenAI 호출·ragas 설치 없음.

실제 채점(_score_samples)은 ragas와 OpenAI가 필요해 다루지 않는다. 대신 채점 전후에서
점수를 틀리게 만들 수 있는 두 지점을 본다: 운영 경로가 아닌 샘플을 거르는지, 채점 실패(NaN)가
평균에 섞였을 때 드러나는지.
"""

from __future__ import annotations

import csv
from datetime import date
from types import SimpleNamespace

import pytest

from app import chat_service
from app.schemas import Notice
from tests.eval import ragas_runner

NAN = float("nan")
CASE = {"id": "c1", "question": "수강신청 기간 알려줘"}


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


def stub_retrieve(mode: str, notices: list[Notice]):
    async def fake(service, question, filters, *args, **kwargs):
        # 운영 코드와 같이 legacy 여도 반환 mode 는 "search" 다. 실제 분기는 trace 에만 남는다.
        returned = "search" if mode == "legacy" else mode
        return notices, [], returned, SimpleNamespace(mode=mode)

    return fake


async def fake_generate(question, filters, notices, *args, **kwargs):
    return "답변", "gpt-4.1-mini"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "mode, notices, reason",
    [
        # 검색 결과가 채워져 있어도 분기 실패면 채점하지 않는다.
        ("legacy", [make_notice("n1", "수강신청 안내")], "분기 실패(legacy)"),
        ("out_of_domain", [], "분기 out_of_domain"),
        ("search", [], "검색 0건"),
    ],
)
async def test_collect_sample_skips_non_production_samples(
    monkeypatch, mode, notices, reason
) -> None:
    monkeypatch.setattr(ragas_runner, "_retrieve_references", stub_retrieve(mode, notices))
    monkeypatch.setattr(ragas_runner, "_generate_with_openai", fake_generate)

    sample, got = await ragas_runner._collect_sample(None, CASE)

    assert sample is None
    assert got == reason


@pytest.mark.anyio
async def test_collect_sample_truncates_context_like_answer_prompt(monkeypatch) -> None:
    content = "가" * 2000
    notice = make_notice("n1", "수강신청 안내", content=content)
    monkeypatch.setattr(ragas_runner, "_retrieve_references", stub_retrieve("search", [notice]))
    monkeypatch.setattr(ragas_runner, "_generate_with_openai", fake_generate)

    sample, reason = await ragas_runner._collect_sample(None, CASE)

    assert reason == ""
    assert sample["response"] == "답변"
    # 답변 LLM이 본 본문과 같은 길이로 잘라 채점해야 한다.
    assert sample["retrieved_contexts"] == [
        chat_service.truncate(content, chat_service.CONTEXT_CONTENT_CHARS)
    ]


@pytest.mark.anyio
async def test_collect_sample_pins_today_to_snapshot_reference_date(monkeypatch) -> None:
    seen: dict[str, object] = {}

    async def fake_retrieve(service, question, filters, *args, today=None, **kwargs):
        seen["retrieve"] = today
        return [make_notice("n1", "수강신청 안내")], [], "search", SimpleNamespace(mode="search")

    async def fake_gen(question, filters, notices, *args, today=None, **kwargs):
        seen["generate"] = today
        return "답변", "gpt-4.1-mini"

    monkeypatch.setattr(ragas_runner, "_retrieve_references", fake_retrieve)
    monkeypatch.setattr(ragas_runner, "_generate_with_openai", fake_gen)

    await ragas_runner._collect_sample(None, CASE, today=date(2026, 9, 14))

    # 분기·rerank·답변 모두 실행 날짜가 아니라 스냅샷 기준일을 오늘로 봐야 한다.
    assert seen == {"retrieve": date(2026, 9, 14), "generate": date(2026, 9, 14)}


def _rows_with_failures() -> list[dict]:
    return [
        {"case_id": "c1", "faithfulness": 1.0, "context_precision_without_reference": 0.5},
        {"case_id": "c2", "faithfulness": NAN, "context_precision_without_reference": 1.0},
        {"case_id": "c3", "faithfulness": 0.5, "context_precision_without_reference": NAN},
    ]


def test_average_excludes_nan_and_counts_are_reported() -> None:
    rows = _rows_with_failures()

    assert ragas_runner.summarize(rows) == {
        "faithfulness": 0.75,
        "context_precision_without_reference": 0.75,
    }
    assert ragas_runner.valid_counts(rows) == {
        "faithfulness": 2,
        "context_precision_without_reference": 2,
    }


def test_report_warns_when_average_uses_partial_samples() -> None:
    report = ragas_runner.format_report(_rows_with_failures(), ["c4(검색 0건)"])

    assert "faithfulness 2/3" in report
    assert "context_precision_without_reference 2/3" in report
    assert "스킵: c4(검색 0건)" in report


def test_report_has_no_warning_when_every_sample_scored() -> None:
    rows = [{"case_id": "c1", "faithfulness": 1.0, "context_precision_without_reference": 1.0}]

    assert "주의" not in ragas_runner.format_report(rows, [])


def test_history_csv_records_valid_counts(tmp_path, monkeypatch) -> None:
    path = tmp_path / "eval_history.csv"
    monkeypatch.setattr(ragas_runner, "HISTORY_CSV_PATH", path)

    ragas_runner.append_history(
        _rows_with_failures(),
        ["c4(검색 0건)"],
        run_ts="2026-09-14_000000",
        judge_model="gpt-4.1-mini",
        snapshot="snapshot-test",
        dump=None,
    )

    with path.open(encoding="utf-8") as f:
        [row] = list(csv.DictReader(f))
    assert (row["snapshot"], row["scored"], row["skipped"]) == ("snapshot-test", "3", "1")
    assert (row["faithfulness"], row["faithfulness_n"]) == ("0.7500", "2")
    assert row["context_precision_without_reference_n"] == "2"
