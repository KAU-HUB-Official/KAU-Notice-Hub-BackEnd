# KAU Notice Hub BackEnd

FastAPI 기반 공지 API 서버다. MVP 저장소는 JSON 파일이며, `app/crawler`의 크롤러가 전체 스냅샷 JSON을 atomic 교체한다.

## 문서

| 문서 | 내용 |
| --- | --- |
| [docs/API_SPEC.md](docs/API_SPEC.md) | API 계약과 Swagger UI 경로 |
| [docs/CLASSIFICATION.md](docs/CLASSIFICATION.md) | 공지 대분류/중분류/source 필터 기준 |
| [docs/CRAWLING_UPDATE.md](docs/CRAWLING_UPDATE.md) | 크롤러 JSON 게시 정책 |
| [docs/crawler/README.md](docs/crawler/README.md) | 통합 크롤러 구조와 운영 문서 |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | 로컬 실행과 Docker Compose 배포 |
| [docs/ERD.md](docs/ERD.md) | JSON 논리 모델과 PostgreSQL 전환 모델 |

## 로컬 실행

```bash
python3 -m pip install -e '.[dev]'
uvicorn app.main:app --reload --port 8000
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

## 크롤러 게시

기본값은 내장 크롤러(`python3 -m app.crawler.main`)를 실행한다. 별도 명령을 넘길 때는 `CRAWLER_COMMAND`가 `$CRAWLER_OUTPUT_PATH`에 병합된 전체 JSON 스냅샷을 쓰면 된다.

```bash
NOTICE_JSON_PATH=./data/kau_official_posts.json \
bash scripts/run_incremental_crawl_publish.sh
```

## Docker

```bash
docker compose up -d --build api
docker compose --profile proxy up -d --build
```
