import asyncio
import json
from pathlib import Path

import pytest

from app import crawler_scheduler, notice_auto_label
from app.config import Settings
from app.ingest import ingest_json_snapshot
from app.notice_auto_label import (
    NoticeForLabel,
    decide,
    label_unlabeled_notices,
    label_with_llm,
    normalize_audiences,
)
from app.sqlite_repository import SqliteNoticeRepository


def _post(seq: int, board: str | None, title: str, content: str = "본문") -> dict:
    post = {
        "title": title,
        "content": content,
        "published_at": "2026-10-14",
        "original_url": f"https://kau.ac.kr/a.php?seq={seq}",
        "source_name": "테스트 게시판",
        "attachments": [{"name": "안내.pdf", "url": "https://kau.ac.kr/f.pdf"}],
    }
    if board:
        post["board_key"] = board
    return post


def _notice(title: str = "제목", body: str = "본문") -> NoticeForLabel:
    return NoticeForLabel(
        url="https://kau.ac.kr/a.php?seq=1",
        board="general_notice",
        board_name="일반공지",
        title=title,
        body=body,
        date="2026-10-14",
        attachment_names=("안내.pdf",),
    )


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# --- 게시판 규칙 (noticebench/board_rules.py decide와 같은 결과) ---


@pytest.mark.parametrize(
    ("board", "title", "body", "expected"),
    [
        ("bid_notice", "청소 용역 입찰", "", ("rule", ("외부",), ())),
        ("research_notice", "연구비 집행 안내", "", ("rule", ("교직원",), ())),
        ("research_notice", "연구원 채용 공고", "", ("rule", ("외부",), ())),
        ("amtc_notice", "교육생 모집", "", ("rule", ("부속기관교육생",), ())),
        ("gradbus_notice", "등록 안내", "", ("rule", ("항공경영대학원생",), ())),
        ("gradbus_notice", "최고위과정 모집", "", ("llm", (), ())),
        ("college_gc91652_notice", "휴학 안내", "", ("rule", ("항공우주정책대학원생",), ())),
        ("general_notice", "장학 안내", "", ("llm", (), ())),
        ("software_department_notice", "캡스톤 발표회", "학과 학생 대상", ("rule", ("학부재학생",), ())),
        ("software_department_notice", "대학원 진학 설명회", "", ("llm", (), ())),
        ("software_department_notice", "특강 안내", "누구나 참여 가능", ("llm", (), ())),
        ("materials_grad_notice", "세미나 안내", "", ("rule", ("일반대학원생",), ())),
        (None, "제목", "", ("llm", (), ())),
    ],
)
def test_decide_follows_board_rules(board, title, body, expected) -> None:
    decision = decide(board, title, body)
    assert (decision.by, decision.audiences, decision.excludes) == expected


def test_decide_adds_freshmen_exclusion_on_department_course_registration() -> None:
    decision = decide(
        "software_department_notice",
        "2026학년도 1학기 수강신청 안내",
        "재학생 수강신청 일정입니다.\n신·편입생은 2/24~25 별도 진행 예정입니다.",
    )
    assert decision.audiences == ("학부재학생",)
    assert decision.excludes == ("신입생·편입생",)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["학부재학생", "일반대학원생", "항공경영대학원생", "항공우주정책대학원생"], ()),
        (["학부재학생", "일반대학원생", "항공경영대학원생", "항공우주정책대학원생", "교직원"], ()),
        (["외부", "학부재학생", "외부"], ("학부재학생", "외부")),
        (["일반대학원생", "학부재학생"], ("학부재학생", "일반대학원생")),
        (["모르는코드"], ()),
    ],
)
def test_normalize_audiences(values, expected) -> None:
    assert normalize_audiences(values) == expected


# --- LLM 호출 ---


class _FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


def _openai_payload(result: dict) -> dict:
    return {
        "output": [
            {"content": [{"type": "output_text", "text": json.dumps(result, ensure_ascii=False)}]}
        ]
    }


@pytest.fixture()
def fake_openai(monkeypatch):
    state: dict = {"response": None, "calls": []}

    def fake_post(url, **kwargs):
        state["calls"].append(kwargs)
        response = state["response"]
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(notice_auto_label.requests, "post", fake_post)
    return state


def test_label_with_llm_sends_structured_request_and_parses(fake_openai) -> None:
    fake_openai["response"] = _FakeResponse(
        200, _openai_payload({"audiences": ["교직원", "외부"], "excludes": [], "reason": "근거"})
    )

    result = label_with_llm(_notice(), api_key="sk-test", model="gpt-4.1-mini")

    assert result == (("교직원", "외부"), (), "근거")
    payload = fake_openai["calls"][0]["json"]
    assert payload["model"] == "gpt-4.1-mini"
    assert payload["temperature"] == 0
    assert payload["text"]["format"]["strict"] is True
    text = payload["input"][0]["content"][0]["text"]
    assert "게시판: 일반공지 (general_notice)" in text
    assert "첨부: 안내.pdf" in text


def test_label_with_llm_keeps_freshmen_exclusion_only_for_registration_series(fake_openai) -> None:
    fake_openai["response"] = _FakeResponse(
        200,
        _openai_payload({"audiences": ["학부재학생"], "excludes": ["신입생·편입생"], "reason": ""}),
    )

    registration = label_with_llm(_notice("수강신청 안내"), api_key="k", model="m")
    leave = label_with_llm(_notice("복학 신청 안내"), api_key="k", model="m")

    assert registration[1] == ("신입생·편입생",)
    assert leave[1] == ()


def test_label_with_llm_truncates_long_body(fake_openai) -> None:
    fake_openai["response"] = _FakeResponse(
        200, _openai_payload({"audiences": [], "excludes": [], "reason": ""})
    )

    label_with_llm(_notice(body="가" * 5000), api_key="k", model="m")

    text = fake_openai["calls"][0]["json"]["input"][0]["content"][0]["text"]
    assert "가" * notice_auto_label.LLM_BODY_MAX_CHARS + "\n(본문 잘림)" in text
    assert "가" * (notice_auto_label.LLM_BODY_MAX_CHARS + 1) not in text


@pytest.mark.parametrize(
    "response",
    [
        _FakeResponse(500, {}),
        _FakeResponse(200, {"output": [{"content": [{"type": "output_text", "text": "not json"}]}]}),
        _FakeResponse(200, _openai_payload({"reason": "칸 없음"})),
        notice_auto_label.requests.Timeout("slow"),
    ],
)
def test_label_with_llm_returns_none_on_failure(fake_openai, response) -> None:
    fake_openai["response"] = response
    assert label_with_llm(_notice(), api_key="k", model="m") is None


# --- 실행 ---


@pytest.fixture()
def snapshot(tmp_path: Path) -> dict[str, Path]:
    json_path = tmp_path / "notices.json"
    json_path.write_text(
        json.dumps(
            [
                _post(1, "general_notice", "연구 라벨이 있는 공지"),
                _post(2, "bid_notice", "입찰 공고"),
                _post(3, "general_notice", "LLM이 볼 공지"),
                _post(4, "event_notice", "LLM이 실패할 공지"),
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    labels_path = tmp_path / "notice_labels.jsonl"
    labels_path.write_text(
        json.dumps({"url": "http://www.kau.ac.kr/a.php?seq=1", "audiences": ["교직원"], "excludes": []})
        + "\n",
        encoding="utf-8",
    )
    return {
        "json": json_path,
        "labels": labels_path,
        "auto": tmp_path / "notice_labels_auto.jsonl",
        "db": tmp_path / "notices.db",
    }


@pytest.fixture()
def fake_llm(monkeypatch):
    calls: list[str] = []

    def fake(notice, *, api_key, model):
        calls.append(notice.title)
        if "실패" in notice.title:
            return None
        return (("학부재학생",), (), "재학생 대상")

    monkeypatch.setattr(notice_auto_label, "label_with_llm", fake)
    return calls


def _run(paths: dict[str, Path], **overrides):
    kwargs = {
        "json_path": paths["json"],
        "labels_path": paths["labels"],
        "auto_labels_path": paths["auto"],
        "api_key": "sk-test",
        "model": "gpt-4.1-mini",
        "max_llm_calls": 10,
    }
    kwargs.update(overrides)
    return label_unlabeled_notices(**kwargs)


def test_label_unlabeled_notices_uses_rule_then_llm_and_skips_research(snapshot, fake_llm) -> None:
    result = _run(snapshot)

    assert (result.candidates, result.rule_labeled, result.llm_labeled, result.llm_failed) == (3, 1, 1, 1)
    rows = {row["url"]: row for row in _read_jsonl(snapshot["auto"])}
    assert set(rows) == {"https://kau.ac.kr/a.php?seq=2", "https://kau.ac.kr/a.php?seq=3"}
    assert rows["https://kau.ac.kr/a.php?seq=2"]["audiences"] == ["외부"]
    assert rows["https://kau.ac.kr/a.php?seq=2"]["label_source"] == "auto_rule"
    assert rows["https://kau.ac.kr/a.php?seq=3"]["label_source"] == "auto_llm"
    assert rows["https://kau.ac.kr/a.php?seq=3"]["model"] == "gpt-4.1-mini"
    assert fake_llm == ["LLM이 볼 공지", "LLM이 실패할 공지"]


def test_label_unlabeled_notices_retries_only_failed_notices(snapshot, fake_llm) -> None:
    _run(snapshot)
    fake_llm.clear()

    result = _run(snapshot)

    assert result.candidates == 1
    assert fake_llm == ["LLM이 실패할 공지"]
    assert len(_read_jsonl(snapshot["auto"])) == 2


def test_label_unlabeled_notices_respects_llm_budget_and_missing_key(snapshot, fake_llm) -> None:
    no_key = _run(snapshot, api_key=None)
    assert (no_key.rule_labeled, no_key.llm_labeled, no_key.llm_skipped) == (1, 0, 2)
    assert fake_llm == []

    limited = _run(snapshot, max_llm_calls=1)
    assert (limited.llm_labeled, limited.llm_skipped) == (1, 1)


def test_ingest_prefers_research_label_over_auto_label(snapshot, fake_llm) -> None:
    _run(snapshot)
    # 연구 라벨이 있는 공지에도 자동 라벨이 남아 있다면(예: 연구 라벨이 나중에 생김) 연구 라벨이 이긴다.
    with snapshot["auto"].open("a", encoding="utf-8") as file:
        file.write(json.dumps({"url": "https://kau.ac.kr/a.php?seq=1", "audiences": ["외부"], "excludes": []}) + "\n")

    ingest_json_snapshot(
        json_path=snapshot["json"],
        db_path=snapshot["db"],
        labels_path=snapshot["labels"],
        auto_labels_path=snapshot["auto"],
    )

    notices = asyncio.run(SqliteNoticeRepository(snapshot["db"]).list_all())
    by_url = {notice.url: notice.targetAudiences for notice in notices}
    assert by_url == {
        "https://kau.ac.kr/a.php?seq=1": ["교직원"],
        "https://kau.ac.kr/a.php?seq=2": ["외부"],
        "https://kau.ac.kr/a.php?seq=3": ["학부재학생"],
        "https://kau.ac.kr/a.php?seq=4": None,
    }


def test_ingest_without_auto_labels_file_does_not_warn(snapshot, caplog) -> None:
    with caplog.at_level("WARNING"):
        ingest_json_snapshot(
            json_path=snapshot["json"],
            db_path=snapshot["db"],
            labels_path=snapshot["labels"],
            auto_labels_path=snapshot["auto"],
        )
    assert "not found" not in caplog.text


# --- 크롤러 스케줄러 연결 ---


def _publish(tmp_path: Path, monkeypatch, *, enabled: bool, labeler) -> None:
    final_path = tmp_path / "notices.json"
    final_path.write_text("[]", encoding="utf-8")

    def fake_crawl_all_notices(*, max_pages: int, output_path: Path):
        posts = [_post(2, "bid_notice", "입찰 공고")]
        output_path.write_text(json.dumps(posts, ensure_ascii=False), encoding="utf-8")
        return posts, []

    monkeypatch.setattr(crawler_scheduler, "_crawl_all_notices", fake_crawl_all_notices)
    monkeypatch.setattr(crawler_scheduler, "label_unlabeled_notices", labeler)
    crawler_scheduler.publish_crawler_snapshot(
        Settings(
            notice_json_path=final_path,
            notice_db_path=tmp_path / "notices.db",
            notice_labels_path=tmp_path / "notice_labels.jsonl",
            notice_auto_labels_path=tmp_path / "notice_labels_auto.jsonl",
            notice_auto_label_enabled=enabled,
            openai_api_key="sk-test",
            crawler_min_records=1,
            crawler_min_retain_ratio=0.0,
        )
    )


def test_publish_labels_before_ingest_when_enabled(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict] = []

    def labeler(**kwargs):
        calls.append(kwargs)
        Path(kwargs["auto_labels_path"]).write_text(
            json.dumps({"url": "https://kau.ac.kr/a.php?seq=2", "audiences": ["외부"], "excludes": []}) + "\n",
            encoding="utf-8",
        )

    _publish(tmp_path, monkeypatch, enabled=True, labeler=labeler)

    assert calls and calls[0]["api_key"] == "sk-test"
    notices = asyncio.run(SqliteNoticeRepository(tmp_path / "notices.db").list_all())
    assert [notice.targetAudiences for notice in notices] == [["외부"]]


def test_publish_skips_labeling_when_disabled(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict] = []
    _publish(tmp_path, monkeypatch, enabled=False, labeler=lambda **kwargs: calls.append(kwargs))
    assert calls == []


def test_publish_still_ingests_when_labeling_fails(tmp_path: Path, monkeypatch) -> None:
    def labeler(**kwargs):
        raise RuntimeError("boom")

    _publish(tmp_path, monkeypatch, enabled=True, labeler=labeler)

    notices = asyncio.run(SqliteNoticeRepository(tmp_path / "notices.db").list_all())
    assert [notice.targetAudiences for notice in notices] == [None]
