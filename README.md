# KAU Notice Hub BackEnd

FastAPI 기반 공지 API 서버다. 크롤러는 전체 스냅샷 JSON을 atomic 교체하고, 그 직후 `app/ingest.py`가 SQLite DB(`NOTICE_DB_PATH`)에 반영한다. API는 SQLite를 읽고, DB가 없으면 JSON에서 자동 부트스트랩한다. 공지 `content`는 Markdown 문자열로 저장되며, 프론트엔드는 Markdown renderer로 상세 페이지를 그린다.

## 문서

| 문서 | 내용 |
| --- | --- |
| [AGENTS.md](AGENTS.md) | 에이전트 작업 규칙과 운영 체크리스트 |
| [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) | 현재 프로젝트 구조와 런타임 흐름 |
| [docs/API_SPEC.md](docs/API_SPEC.md) | API 계약과 Swagger UI 경로 |
| [docs/CLASSIFICATION.md](docs/CLASSIFICATION.md) | 공지 대분류/중분류/source 필터 기준 |
| [docs/CRAWLING_UPDATE.md](docs/CRAWLING_UPDATE.md) | 크롤러 JSON 게시 정책 |
| [docs/RAG_PLAN.md](docs/RAG_PLAN.md) | 공지 기반 RAG 동작 기준 |
| [docs/crawler/README.md](docs/crawler/README.md) | 통합 크롤러 구조와 운영 문서 |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | 로컬 실행, Docker Compose, GitHub Actions 배포 |
| [docs/ERD.md](docs/ERD.md) | SQLite 스키마와 JSON 원천 모델 |

## 프로젝트 구조 요약

```text
app/             FastAPI 앱, service/repository, SQLite ingest, 검색/분류
app/api/         health, notices, chat router
app/crawler/     KAU 공지 크롤러 client/parser/service/policy
scripts/         수동 JSON 스냅샷 publish 스크립트
tests/           pytest 테스트와 retrieval eval case
docs/            API, 배포, ERD, RAG, 크롤러 운영 문서
data/            로컬 런타임 JSON/SQLite 저장소 (.gitkeep만 커밋)
```

런타임 기준 흐름은 `NOTICE_JSON_PATH` 전체 스냅샷을 크롤러가 atomic 게시하고, `app/ingest.py`가 같은 데이터를 `NOTICE_DB_PATH` SQLite DB로 atomic 반영하는 구조다. API는 SQLite를 우선 읽고, DB를 만들 수 없을 때 JSON repository로 폴백한다.

## 로컬 실행

```bash
python3 -m pip install -e '.[dev]'
uvicorn app.main:app --reload --port 8000
```

## 서버 종료

터미널에서 직접 실행 중이면 `Ctrl+C`로 종료한다.

백그라운드 실행 중인 로컬 서버를 종료할 때:

```bash
pkill -f "uvicorn app.main:app"
```

`screen` 세션으로 실행한 서버를 종료할 때:

```bash
screen -S kau-notice-backend -X quit
```

확인:

```bash
curl http://localhost:8000/health
curl 'http://localhost:8000/api/notices?page=1&pageSize=5'
```

챗봇 호출 (RAG_ENABLED=true + OPENAI_API_KEY가 있어야 LLM 답변, 아니면 local fallback):

```bash
curl -sS -X POST http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"수강신청 알려줘"}'
```

후속 질문은 `history`에 직전 대화를 함께 보낸다. UI에서 단계별 진행("검색중 → 검색 완료 → 답변")을 그리려면 SSE 엔드포인트 `POST /api/chat/stream`을 사용한다. 자세한 동작은 [docs/API_SPEC.md](docs/API_SPEC.md), [docs/RAG_PLAN.md](docs/RAG_PLAN.md)를 참고한다.

API 문서 UI:

```text
http://localhost:8000/docs
http://localhost:8000/redoc
http://localhost:8000/openapi.json
```

## 테스트

```bash
pytest -q
```

GitHub Actions의 `CI / test`는 push와 pull request에서 실행된다. `main` 병합 또는 직접 push 전에 로컬에서도 테스트를 실행한다.

## k6 부하 테스트

로컬 API 서버를 실행한 뒤 k6 스크립트를 실행한다. 아래 명령은 `k6` CLI가 PATH에 설치되어 있어야 한다.

```bash
uvicorn app.main:app --reload --port 8000
k6 run load-tests/k6/api-load-test.js
```

기본 `PROFILE=smoke`는 짧은 검증용이다. 로컬에서 조금 더 긴 테스트를 돌릴 때:

```bash
PROFILE=local BASE_URL=http://localhost:8000 k6 run load-tests/k6/api-load-test.js
```

주요 옵션:

| 환경변수 | 기본값 | 설명 |
| --- | --- | --- |
| `BASE_URL` | `http://localhost:8000` | 부하 테스트 대상 API base URL |
| `PROFILE` | `smoke` | `smoke`, `local`, `stress`, `remote_100` 중 하나 |
| `NOTICE_ID` | 없음 | 지정하면 상세 API를 해당 공지 ID로 호출 |
| `INCLUDE_CHAT` | `false` | `true`면 `/api/chat`도 포함. OpenAI 설정이 켜진 환경에서는 외부 호출/비용이 생길 수 있음 |
| `SEARCH_TERMS` | 주요 한국어 검색어 | 쉼표로 구분한 검색어 목록 |

운영 서버 대상 부하 테스트는 반드시 대상 URL과 강도를 별도로 확인한 뒤 실행한다.

원격 테스트 배포 서버에 100 VU 부하를 줄 때:

```bash
PROFILE=remote_100 BASE_URL=https://api.example.com k6 run load-tests/k6/api-load-test.js
```

## 크롤러 게시

기본값은 내장 크롤러(`python3 -m app.crawler.main`)를 실행한다. 별도 명령을 넘길 때는 `CRAWLER_COMMAND`가 `$CRAWLER_OUTPUT_PATH`에 병합된 전체 JSON 스냅샷을 쓰면 된다.

```bash
NOTICE_JSON_PATH=./data/kau_official_posts.json \
bash scripts/run_incremental_crawl_publish.sh
```

## 기존 공지 본문을 Markdown으로 일괄 재파싱

신규 크롤은 자동으로 Markdown 본문을 만들지만 마이그레이션 이전에 수집된 공지는 plain text다. 기존 JSON의 모든 공지를 detail 페이지에서 다시 fetch 후 새 파서로 재파싱해 `content`만 Markdown으로 교체:

```bash
# in-place (atomic rename, 안전)
.venv/bin/python -m scripts.refresh_markdown_content \
  --input data/kau_official_posts.json --sleep 0.3
```

`--limit N` 옵션으로 처음 N건만 시범 실행, `--sleep` 초로 KAU 서버 요청 간격을 조절한다. 약 2,000건 기준 0.3s 간격으로 20–30분 소요. 실패한 공지는 기존 content를 유지하므로 중간에 끊겨도 안전.

## 내장 크롤러 스케줄러

Docker Compose 배포에서는 API 컨테이너가 시작 직후 1회 크롤링하고, 이후 3시간마다 백그라운드에서 JSON을 갱신한다.

```env
CRAWLER_SCHEDULER_ENABLED=true
CRAWLER_INTERVAL_SECONDS=10800
CRAWLER_RUN_ON_STARTUP=true
```

## Docker

```bash
docker compose up -d --build api
docker compose --profile proxy up -d --build
```

운영 배포는 `main`에 merge 또는 push되면 GitHub Actions가 Lightsail 서버에서 `git pull`과 `docker compose --profile proxy up -d --build`를 실행한다. 외부 공개 포트는 Caddy의 80/443이며, API 8000 포트는 host의 `127.0.0.1`에만 바인딩한다.

Docker Compose 서버 종료:

```bash
docker compose down
```
