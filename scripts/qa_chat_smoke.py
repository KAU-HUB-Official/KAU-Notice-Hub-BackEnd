"""실제 OpenAI 호출로 /api/chat 2단계 rerank + 분기 파이프라인을 QA하는 스모크 스크립트.

mock 단위 테스트(tests/test_chat_rag.py)는 분기/폴백 '로직'만 검증한다. 이 스크립트는
GPT가 실제로 분기(search/history/out_of_domain)를 의도대로 고르고, rerank가 후보를
제대로 좁히는지를 실호출로 본다. AGENTS.md의 "프롬프트/가드 분기를 바꾸면 실제 OpenAI
호출 QA로 회귀를 검증한다" 규칙용이다.

실행:
    RAG_ENABLED=true uvicorn 없이 in-process로 ask_notice_question을 직접 호출한다.
    OPENAI_API_KEY/OPENAI_MODEL은 .env에서 읽는다.

    python3 scripts/qa_chat_smoke.py

비용: gpt-4.1-mini로 시나리오당 1~3회 호출, 전체 십수 회 수준.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

# app.config 첫 호출 전에 RAG 플래그를 강제로 켠다(.env의 RAG_ENABLED=false를 덮어씀).
os.environ["RAG_ENABLED"] = "true"
os.environ["RAG_QUERY_EXTRACTION_ENABLED"] = "true"

from app import chat_service  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.dependencies import get_notice_service  # noqa: E402
from app.schemas import ChatMessage  # noqa: E402


# --- LLM 호출을 감싸 어떤 종류의 호출이 어떤 출력을 냈는지 기록 ---
_orig_call = chat_service._call_openai_sync
_calls: list[tuple[str, str]] = []


def _classify(system_prompt: str) -> str:
    if "검색 분기" in system_prompt:
        return "triage"
    if "공지 검색 보조자" in system_prompt:
        return "rerank"
    if "공지 안내 도우미" in system_prompt:
        return "answer"
    return "other"


def _wrapped_call(api_key, model, system_prompt, messages):
    out = _orig_call(api_key, model, system_prompt, messages)
    kind = _classify(system_prompt)
    preview = (out or "").strip().replace("\n", " ")
    limit = 200 if kind in {"triage", "rerank"} else 60
    _calls.append((kind, preview[:limit]))
    return out


chat_service._call_openai_sync = _wrapped_call


# --- 분기 로그(rag_*) 캡처 ---
_logs: list[str] = []


class _ListHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        _logs.append(record.getMessage())


_handler = _ListHandler()
_handler.setLevel(logging.INFO)
_logger = logging.getLogger("app.chat_service")
_logger.setLevel(logging.INFO)
_logger.addHandler(_handler)


def _reset() -> None:
    _calls.clear()
    _logs.clear()


async def run_case(svc, label, question, *, history=None, expect=None):
    _reset()
    ans = await chat_service.ask_notice_question(svc, question, history=history)
    print("\n" + "=" * 78)
    print(f"[{label}]  기대 분기: {expect}")
    print(f"질문: {question!r}" + (f"  (history {len(history)}개)" if history else ""))
    print(f"LLM 호출 순서: {[k for k, _ in _calls]}")
    for kind, preview in _calls:
        if kind in {"triage", "rerank"}:
            print(f"   └ {kind} 출력: {preview}")
    branch_logs = [m for m in _logs if m.startswith("rag_")]
    if branch_logs:
        print(f"분기 로그: {branch_logs}")
    print(f"usedFallback={ans.usedFallback}  model={ans.model}  refs={len(ans.references)}")
    for ref in ans.references[:6]:
        print(f"   - {ref.id} | {ref.title} | {ref.date}")
    answer_preview = ans.answer.strip().replace("\n", " ")
    print(f"답변: {answer_preview[:400]}")
    return ans


async def run_stream(svc, question):
    _reset()
    print("\n" + "=" * 78)
    print(f"[STREAM]  질문: {question!r}")
    types = []
    async for event in chat_service.stream_notice_question(svc, question):
        types.append(event["type"])
    print(f"이벤트 순서: {types}")


async def main() -> None:
    settings = get_settings()
    if not settings.openai_api_key:
        print("OPENAI_API_KEY가 비어 있습니다. .env에 키를 넣고 다시 실행하세요.")
        sys.exit(1)
    print(
        f"model={settings.openai_model}  candidate_pool={settings.rag_candidate_pool}  "
        f"max_references={settings.rag_max_references}"
    )

    svc = get_notice_service()

    # 1. 기본 검색
    await run_case(svc, "1. search 기본", "장학금 신청 공지 알려줘", expect="search")

    # 2. 도메인 외
    await run_case(svc, "2. out_of_domain", "비트코인 시세 알려줘", expect="out_of_domain")

    # history는 실제 답변으로 시드해 현실적으로 구성
    seed_q = "장학금 신청 공지 알려줘"
    seed = await chat_service.ask_notice_question(svc, seed_q)
    history = [
        ChatMessage(role="user", content=seed_q),
        ChatMessage(role="assistant", content=seed.answer),
    ]

    # 3. 직전 답변 재가공 → history 분기 기대(검색/refs 없음)
    await run_case(
        svc, "3. history 재가공", "방금 답변 더 짧게 요약해줘",
        history=history, expect="history",
    )

    # 4. 후속이지만 본문 사실 필요 → search 기대(history 아님)
    await run_case(
        svc, "4. 후속-본문사실", "그 중 첫 번째 공지 신청 마감일이 언제야?",
        history=history, expect="search",
    )

    # 5. 회귀: 단발 검색
    await run_case(svc, "5. 회귀 단발", "수강신청", expect="search")

    # 6. SSE 3단계 이벤트
    await run_stream(svc, "수강신청 공지 알려줘")

    print("\n" + "=" * 78)
    print("QA 완료. 위에서 각 기대 분기와 실제 동작이 맞는지 확인하세요.")


if __name__ == "__main__":
    asyncio.run(main())
