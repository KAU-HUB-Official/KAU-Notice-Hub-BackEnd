# 백엔드 배포

## 범위
이 문서는 KAU Notice Hub FastAPI 백엔드의 로컬 실행과 Docker Compose 배포 기준을 정의한다.

현재 MVP 구성:

- FastAPI API 서버
- JSON 파일 저장소
- 외부 크롤러 프로세스 또는 crawler container
- 공유 데이터 volume의 `/data/kau_official_posts.json`
- 선택적 Caddy reverse proxy

## 로컬 실행

의존성 설치:

```bash
python3 -m pip install -e '.[dev]'
```

서버 실행:

```bash
NOTICE_JSON_PATH=../MVP/kau_official_posts.json \
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
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

## 환경변수

| 이름 | 예시 | 설명 |
| --- | --- | --- |
| `NOTICE_JSON_PATH` | `/data/kau_official_posts.json` | API 서버가 읽는 전체 공지 JSON 스냅샷 |
| `BACKEND_CORS_ORIGINS` | `https://kau-notice.example.com` | 쉼표로 구분한 허용 frontend origin |
| `OPENAI_API_KEY` | `sk-...` | 예약값. 현재 챗봇은 local fallback 사용 |
| `OPENAI_MODEL` | `gpt-4.1-mini` | 예약값. 향후 OpenAI 연동 모델명 |
| `LOG_LEVEL` | `INFO` | 로그 레벨 |

로컬 예시:

```env
NOTICE_JSON_PATH=./data/kau_official_posts.json
BACKEND_CORS_ORIGINS=http://localhost:3000
OPENAI_MODEL=gpt-4.1-mini
LOG_LEVEL=INFO
```

## Docker Compose

구현 파일은 [../docker-compose.yml](../docker-compose.yml)이다.

API만 실행:

```bash
docker compose up -d --build api
```

API와 Caddy reverse proxy 실행:

```bash
docker compose --profile proxy up -d --build
```

크롤러 1회 실행:

```bash
docker compose --profile tools run --rm crawler
```

현재 compose 구성의 핵심:

```text
api
  -> reads /data/kau_official_posts.json

crawler
  -> runs scripts/run_incremental_crawl_publish.sh
  -> writes /data/kau_official_posts.json atomically
  -> mounts ../Crawler at /crawler

caddy
  -> reverse_proxy api:8000
```

## 데이터 파일 준비

초기 실행 전 `NOTICE_JSON_PATH`에 JSON 배열 파일이 있어야 한다.

로컬:

```bash
mkdir -p data
cp ../MVP/kau_official_posts.json data/kau_official_posts.json
```

Docker volume을 사용할 때는 crawler를 한 번 실행하거나, 운영 서버에서 volume 내부에 초기 JSON을 넣는다.

## 크롤러 주기 실행

크롤러는 API 서버 내부에서 실행하지 않는다. cron, systemd timer, Docker scheduler 중 하나가 `scripts/run_incremental_crawl_publish.sh`를 주기 실행한다.

cron 예시:

```cron
*/60 * * * * cd /opt/kau-notice-backend && docker compose --profile tools run --rm crawler
```

스크립트 상세 정책은 [CRAWLING_UPDATE.md](CRAWLING_UPDATE.md)를 따른다.

## 배포 순서

1. 서버에 Docker와 Docker Compose 설치
2. 백엔드 레포 clone
3. `.env` 작성
4. JSON 데이터 volume 준비
5. `docker compose up -d --build api`
6. `curl http://localhost:8000/health` 확인
7. `curl 'http://localhost:8000/api/notices?page=1&pageSize=5'` 확인
8. Swagger UI `/docs` 확인
9. Caddy 또는 외부 reverse proxy 연결
10. frontend의 API base URL 전환
11. crawler scheduler 등록

## 운영 확인

필수 확인:

```bash
curl https://api.kau-notice.example.com/health
curl 'https://api.kau-notice.example.com/api/notices?page=1&pageSize=5'
```

문서 UI:

```text
https://api.kau-notice.example.com/docs
https://api.kau-notice.example.com/redoc
https://api.kau-notice.example.com/openapi.json
```

로그:

```bash
docker compose logs -f api
docker compose logs -f crawler
docker compose logs -f caddy
```

## 장애 대응 기준

| 상황 | 확인 |
| --- | --- |
| API 서버 다운 | `docker compose ps`, `docker compose logs api` |
| JSON 파싱 실패 | crawler tmp 검증 로그, API 이전 정상 캐시 유지 여부 |
| 크롤링 실패 | `docker compose logs crawler`, 기존 JSON 유지 여부 |
| CORS 에러 | `BACKEND_CORS_ORIGINS`와 frontend origin |
| 데이터 미갱신 | scheduler 실행 여부, JSON mtime, API repository reload |
| Swagger 미노출 | `/docs`, `/openapi.json` 응답 상태 |

## PostgreSQL 전환 후

PostgreSQL 도입 후에는 JSON 공유 volume 의존도를 줄이고, 크롤러 또는 ingestion job이 DB에 upsert한다.

```text
Crawler scheduler
  -> 신규/수정 공지 수집
  -> DB upsert

FastAPI
  -> PostgreSQL 조회
  -> API 응답
```

그 전까지 API 계약은 JSON 저장소 기준으로 유지한다.

