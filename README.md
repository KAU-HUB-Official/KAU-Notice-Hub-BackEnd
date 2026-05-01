# KAU Notice Hub BackEnd

FastAPI 기반 공지 API 서버다. MVP 저장소는 JSON 파일이며, `app/crawler`의 크롤러가 전체 스냅샷 JSON을 atomic 교체한다.

## 문서

| 문서 | 내용 |
| --- | --- |
| [AGENTS.md](AGENTS.md) | 에이전트 작업 규칙과 운영 체크리스트 |
| [docs/API_SPEC.md](docs/API_SPEC.md) | API 계약과 Swagger UI 경로 |
| [docs/CLASSIFICATION.md](docs/CLASSIFICATION.md) | 공지 대분류/중분류/source 필터 기준 |
| [docs/CRAWLING_UPDATE.md](docs/CRAWLING_UPDATE.md) | 크롤러 JSON 게시 정책 |
| [docs/crawler/README.md](docs/crawler/README.md) | 통합 크롤러 구조와 운영 문서 |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | 로컬 실행, Docker Compose, GitHub Actions 배포 |
| [docs/ERD.md](docs/ERD.md) | JSON 논리 모델 |

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

## 크롤러 게시

기본값은 내장 크롤러(`python3 -m app.crawler.main`)를 실행한다. 별도 명령을 넘길 때는 `CRAWLER_COMMAND`가 `$CRAWLER_OUTPUT_PATH`에 병합된 전체 JSON 스냅샷을 쓰면 된다.

```bash
NOTICE_JSON_PATH=./data/kau_official_posts.json \
bash scripts/run_incremental_crawl_publish.sh
```

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
