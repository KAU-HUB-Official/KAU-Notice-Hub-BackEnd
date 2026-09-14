# RAG Evaluation

## 범위

이 문서는 KAU Notice Hub 챗봇/검색 품질을 **수치로 측정**하는 방법을 정의한다. RAG
동작 자체의 기준은 [RAG_PLAN.md](RAG_PLAN.md)를, 단위/통합 테스트 정책은 그쪽 "테스트
계획"을 따른다. 여기서는 답변 품질과 검색 결과의 관련도를 재는 평가 하네스만 다룬다.

답변 품질은 RAGAS 자동 지표 2개와 사람 판정으로 잰다.

| 무엇을 재나 | 방법 | 하네스 | OpenAI 비용 |
| --- | --- | --- | --- |
| 환각 | RAGAS `faithfulness` | `tests/eval/ragas_runner.py` | 발생 |
| 검색 노이즈 | RAGAS `context_precision_without_reference` | `tests/eval/ragas_runner.py` | 발생 |
| 질문에 답했나 | 사람 0/1 판정 | RAGAS 실행별 상세 파일 | 없음 |

평가 질문은 자연어 질문만 모은 전용 셋
[tests/eval/ragas_cases.yml](../tests/eval/ragas_cases.yml)을 쓰고 `question`/`filters`만
사용한다.

> 검색 recall@k/MRR 평가(`tests/eval/runner.py`, `retrieval_cases.yml`)는 삭제했다. 범용
> 질문의 정답을 공지 몇 건으로 임의 고정하거나 제목 일부 글자로 너무 넓게 잡아 점수가 검색
> 품질을 반영하지 못했고, 분기 LLM과 rerank를 거치지 않아 운영 경로와도 달랐다. 더 정확한
> 채점 지표로 대체한다.

RAGAS 평가는 운영 데이터(`data/kau_notice_hub.db`)가 있어야 검색이 동작하고 OpenAI 비용이
들므로, CI에서는 돌리지 않고 필요할 때 CLI로 실행한다.

## 답변 품질 (RAGAS, LLM-as-judge)

답변·검색 품질을 LLM 채점관으로 정량화한다. 모범답안(ground truth) 라벨이 필요 없는
2개 지표만 쓴다.

- `faithfulness` — (답변 생성) 답변이 검색된 context에 충실한가. 환각 탐지.
- `context_precision_without_reference` — (후보 검색·rerank) 검색된 context가
  질문에 관련 있나. 노이즈 비율.

답변이 질문에 실제로 답했는지는 RAGAS `answer_relevancy`로 재지 않고 **사람이 0/1로
판정**한다. `answer_relevancy`는 답변에서 거꾸로 만든 질문과 원 질문의 임베딩 유사도로
채점하는데, 이 서비스의 답변 방식과 맞지 않아 점수가 실제 품질보다 낮게 나왔다
(2026-06-25 실행 13건 평균 0.36).

- 공지에 없는 날짜를 추측하지 않고 "명시되어 있지 않다"고 답하면 얼버무린 답변으로
  보고 0점을 준다. 같은 샘플의 faithfulness는 1.0이었다.
- 기간·대상·방법을 목록으로 정리한 답변은 거꾸로 만든 질문이 원 질문과 달라져 점수가
  낮아진다.

사람 판정은 아래 실행별 상세 파일의 `user_input`과 `response`를 보고 한다. 답변은 실행마다
새로 생성되므로 라벨은 그 실행 결과에만 해당한다.

흐름: 평가셋의 각 질문을 실제 `/api/chat` 파이프라인에 돌려
`(question, retrieved_contexts, response)`를 모은 뒤 ragas collections 메트릭의
`ascore()`로 채점한다(native `llm_factory`, 비동기 클라이언트).
`retrieved_contexts`는 공지마다 `content`를 `build_context`와 같은 길이(1400자)로 잘라
담는다 — 모델이 실제로 본 context를 채점하기 위함이다. 이미지뿐인 공지도 enrichment가
`content`를 실제 텍스트로 채우므로(읽는 본문은 `content` 하나로 단일화) content만으로
충분하다. `search` 분기가 아니거나(도메인외/history) 검색 0건인 케이스는 채점에서 스킵한다.

- 채점관 LLM은 `OPENAI_MODEL`(기본 gpt-4.1-mini)을 재사용한다.
- **OpenAI 채점 호출 비용이 발생**하므로 필요할 때 CLI로만 실행한다.
- 전제: `RAG_ENABLED=true` + `OPENAI_API_KEY`가 있어야 답변이 OpenAI로 생성된다.
  비활성 상태면 답변이 local fallback이라 채점 대상이 아니다.

의존성은 런타임이 아니라 평가 전용 extra로 격리한다. ragas 0.4.x가 모듈 로드 시
`langchain_community.chat_models.vertexai`를 import하는데 이 경로가 langchain-community
0.4(사실상 sunset) 이후 제거돼, `langchain-community>=0.3,<0.4` 핀이 없으면
`import ragas` 자체가 깨진다(`pyproject.toml`의 `eval` extra에 핀으로 고정).

```bash
# 평가 의존성 설치 (런타임 이미지엔 넣지 않는다)
python3 -m pip install -e '.[eval]'

# CLI 보고서 (지표별 평균 표). OPENAI_API_KEY는 .env에서 읽는다.
RAG_ENABLED=true OPENAI_API_KEY=... \
  python -m tests.eval.ragas_runner
```

실행 결과는 두 곳에 남는다.

- **실행별 상세**: `data/ragas_runs/<실행시각>.json`(예: `2026-09-14_153000.json`). 질문·필터·검색 context·생성 답변·
  점수·스킵 목록을 담는다. `data/`는 gitignore 대상이라 로컬 전용이다. 점수표만으론
  낮은 케이스의 원인을 못 보므로, 재실행 없이 실제 답변/context를 열어 진단하거나 사람
  판정을 붙이는 데 쓴다. `RAGAS_DUMP_PATH`로 경로를 강제하고(예: `before.json`/
  `after.json`), 빈 문자열이면 저장하지 않는다.
- **요약 이력**: `tests/eval/eval_history.csv`. 실행 1회가 한 행이며 `run_ts`,
  `judge_model`, `scored`, `skipped`, 지표별 평균, 상세 파일 경로를 담는다. git으로
  추적해 변경 전후를 비교한다.

## 변경 전후 비교 (핵심 용도)

프롬프트·검색 방식·chunk·top-k를 바꾸기 **전후**로 같은 평가셋을 두 번 돌려 숫자를
비교한다. "꽤 좋아졌다"가 아니라 "이 지표가 이만큼 개선됐다"로 말하기 위함이다.

```bash
# 바꾸기 전 기준점
RAG_ENABLED=true python -m tests.eval.ragas_runner | tee before.txt
# … 프롬프트/검색 수정 …
# 바꾼 뒤 재측정
RAG_ENABLED=true python -m tests.eval.ragas_runner | tee after.txt
```

`AVG` 줄을 비교한다. 검색을 바꿨으면 context precision을, 프롬프트를 바꿨으면
faithfulness와 사람 판정(질문에 답했나)을 본다.

## 평가셋 키우기

RAGAS 셋([ragas_cases.yml](../tests/eval/ragas_cases.yml))은 실사용 말투의 자연어 질문
15개로, 서로 다른 intent를 1개씩 커버하고 표현 style과 filter 사용을 섞는다. 모든 질문은
운영 DB의 실제 공지에 grounding 했고, 핵심 검색어로 검색하면 상위 10건이 꽉 차게
반환되도록(단일 공지 매치 제외) 골라 데이터가 일부 prune돼도 검색 0건으로 스킵되지
않게 했다.

질문을 더 추가할 때는 (1) 명백히 KAU 공지 도메인이라 triage가 `search`로 보내고,
(2) 핵심 검색어로 검색하면 1건 이상 나오는지(0건이면 채점 스킵)를 확인한다. 검색
여부는 OpenAI 없이 `find_relevant_notices`로 검증할 수 있다. 챗봇 세션 로깅
(`CHAT_LOGGING_ENABLED`, [API_SPEC.md](API_SPEC.md) 참고)으로 쌓인 실사용 질문을
`chat_sessions.db`에서 뽑아 평가셋을 키울 수 있다.

## 관련 파일

| 영역 | 파일 |
| --- | --- |
| RAGAS 평가셋(자연어 질문) | `tests/eval/ragas_cases.yml` |
| RAGAS 평가 runner | `tests/eval/ragas_runner.py` |
| RAGAS 요약 이력 | `tests/eval/eval_history.csv` (실행 시 append) |
| 평가 의존성 | `pyproject.toml`의 `eval` extra |
