# RAG Evaluation

## 범위

이 문서는 KAU Notice Hub 챗봇/검색 품질을 **수치로 측정**하는 방법을 정의한다. RAG
동작 자체의 기준은 [RAG_PLAN.md](RAG_PLAN.md)를, 단위/통합 테스트 정책은 그쪽 "테스트
계획"을 따른다. 여기서는 "검색이 얼마나 잘 찾나 / 답변이 얼마나 좋은가"를 재는 평가
하네스만 다룬다.

평가는 두 층위로 나눈다. 파이프라인의 어느 단계가 문제인지 분리해서 보기 위함이다.

| 층위 | 무엇을 재나 | 지표 | 하네스 | OpenAI 비용 |
| --- | --- | --- | --- | --- |
| 검색(retrieval) | 정답 공지를 상위 k에 얼마나 잘 찾나 | recall@5, recall@10, MRR | `tests/eval/runner.py` | 없음 |
| 답변 품질(RAGAS) | 환각·검색 노이즈·질문 적합성 | faithfulness, context precision, answer relevancy | `tests/eval/ragas_runner.py` | 발생 |

두 층위 모두 같은 평가셋([tests/eval/retrieval_cases.yml](../tests/eval/retrieval_cases.yml))을
입력으로 쓴다. 케이스는 `question`(+ 선택 `filters`)을 갖고, 검색 평가는 추가로
`must_include_titles`(상위 10건에 떠야 하는 정답 공지 제목 substring)를 라벨로 쓴다.
RAGAS 평가는 라벨을 무시하고 `question`/`filters`만 재사용한다.

두 평가 모두 운영 데이터(`data/kau_notice_hub.db`)가 있어야 검색이 동작하므로, 비용·
데이터 의존성 때문에 기본 `pytest`에서 제외하고 전용 마크로만 실행한다.

## 1. 검색 품질 (recall@k / MRR)

라벨한 "질문 → 정답 공지" 표로, 실제 검색 함수(`find_relevant_notices`)를 돌려 정답이
상위 5/10위 안에 얼마나, 얼마나 위쪽에 들어오는지 평균낸다. LLM 채점이 없어 비용이 없다.

- **recall@5 / recall@10**: 정답들 중 상위 5/10건 안에 든 비율.
- **MRR**: 정답이 처음 등장한 순위의 역수 평균(순위 민감).

실행:

```bash
# CLI 보고서 (케이스별 표 + 평균, assertion 없음)
.venv/bin/python -m tests.eval.runner

# 회귀 가드 (threshold 미만이면 fail)
.venv/bin/python -m pytest -m eval
```

회귀 가드 threshold([tests/test_retrieval_quality.py](../tests/test_retrieval_quality.py)):
recall@5 ≥ 0.70, recall@10 ≥ 0.85, MRR ≥ 0.55. baseline 측정 후 점진적으로 올린다.

> 라벨 기준 시점은 `retrieval_cases.yml` 상단 주석을 따른다. 운영 데이터가 갱신되어
> 정답 공지가 prune되면 `must_include_titles`를 재라벨링한다.

## 2. 답변 품질 (RAGAS, LLM-as-judge)

답변·검색 품질을 LLM 채점관으로 정량화한다. 모범답안(ground truth) 라벨이 필요 없는
3개 지표만 쓴다.

- `faithfulness` — (답변 생성) 답변이 검색된 context에 충실한가. 환각 탐지.
- `context_precision_without_reference` — (후보 검색·rerank) 검색된 context가
  질문에 관련 있나. 노이즈 비율.
- `answer_relevancy` — (답변 생성) 답변이 질문에 실제로 답했나. 임베딩을 사용.

흐름: 평가셋의 각 질문을 실제 `/api/chat` 파이프라인에 돌려
`(question, retrieved_contexts, response)`를 모은 뒤 ragas collections 메트릭의
`ascore()`로 채점한다(native `llm_factory` + `OpenAIEmbeddings`, 비동기 클라이언트).
`retrieved_contexts`는 검색된 공지 본문을 `build_context`와 같은 길이(1400자)로 잘라
모델이 실제로 본 context를 채점한다. `search` 분기가 아니거나(도메인외/history) 검색
0건인 케이스는 채점에서 스킵한다.

- 채점관 LLM은 `OPENAI_MODEL`(기본 gpt-4.1-mini)을 재사용한다.
- `answer_relevancy`는 임베딩이 필요해 `RAGAS_EMBEDDING_MODEL`(기본
  `text-embedding-3-small`)을 추가로 호출한다. 이 임베딩은 채점기 내부 계산용이며
  검색 파이프라인(키워드 검색)과는 무관하다.
- **OpenAI 채점 호출 비용이 발생**하므로 기본 `pytest`에서 제외되고, `ragas` 마크로만
  실행한다([tests/test_chat_ragas.py](../tests/test_chat_ragas.py)).
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

# pytest 회귀 가드 (비용 발생). -s 로 점수표를 콘솔에 출력.
RAG_ENABLED=true OPENAI_API_KEY=... \
  pytest -m ragas -s
```

점수 하한 threshold는 baseline 측정 후 `tests/test_chat_ragas.py`에서 점진적으로
올린다(현재는 지표가 정상 산출되는지와 `[0,1]` 범위만 검증).

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

`AVG` 줄을 비교한다. 검색을 바꿨으면 recall/context precision을, 프롬프트를 바꿨으면
faithfulness/answer relevancy를 본다.

## 평가셋 키우기

`retrieval_cases.yml`의 질문은 retrieval 디버깅용이라 짧은 키워드형이 많다. 실제 답변
품질을 보려면 사용자 말투의 질문을 늘리는 게 좋다. 챗봇 세션 로깅
(`CHAT_LOGGING_ENABLED`, [API_SPEC.md](API_SPEC.md) 참고)으로 쌓인 실사용 질문을
`chat_sessions.db`에서 뽑아 평가셋을 키울 수 있다.

## 관련 파일

| 영역 | 파일 |
| --- | --- |
| 평가셋(공통) | `tests/eval/retrieval_cases.yml` |
| 검색 평가 runner | `tests/eval/runner.py` |
| 검색 회귀 가드 | `tests/test_retrieval_quality.py` (`pytest -m eval`) |
| RAGAS 평가 runner | `tests/eval/ragas_runner.py` |
| RAGAS 회귀 가드 | `tests/test_chat_ragas.py` (`pytest -m ragas`) |
| 평가 의존성 | `pyproject.toml`의 `eval` extra |
