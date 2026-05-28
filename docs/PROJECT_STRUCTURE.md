# 프로젝트 구조

## 범위

이 문서는 현재 `KAU-Notice-Hub-BackEnd` 저장소의 코드 배치와 런타임 흐름을 빠르게 파악하기 위한 구조 문서다.

백엔드는 FastAPI API 서버, 내장 KAU 공지 크롤러, SQLite 저장소, JSON 스냅샷 안전망으로 구성된다.

## 루트 구조

| 경로 | 역할 |
| --- | --- |
| `app/` | FastAPI 앱, API router, service/repository 계층, SQLite ingest, 검색/분류 로직 |
| `app/api/` | `/health`, `/api/notices`, `/api/chat` router |
| `app/crawler/` | KAU 공지 크롤러 본체. client, parser, service, policy로 분리 |
| `scripts/` | 수동 운영 스크립트. 현재 `run_incremental_crawl_publish.sh`가 JSON 스냅샷을 atomic 게시 |
| `tests/` | pytest 테스트와 retrieval eval case |
| `docs/` | API, 배포, ERD, RAG, 크롤러 운영 문서 |
| `data/` | 로컬 JSON/SQLite 런타임 데이터 디렉터리. `.gitkeep`만 커밋 |
| `.github/workflows/` | CI 테스트와 Lightsail 배포 workflow |
| `Dockerfile` | API/crawler 공용 Python 이미지 |
| `docker-compose.yml` | API, one-off crawler tool, Caddy reverse proxy 서비스 |
| `Caddyfile` | Caddy reverse proxy 설정 |
| `.env.example` | 로컬/운영 환경변수 예시. 실제 `.env`는 커밋 금지 |

## 런타임 흐름

```text
FastAPI startup
  -> app/dependencies.py가 repository 선택
  -> NOTICE_DB_PATH SQLite 스키마가 맞으면 SQLite 사용
  -> DB가 없거나 스키마가 다르면 NOTICE_JSON_PATH에서 app/ingest.py로 atomic DB 생성
  -> JSON도 없으면 JsonNoticeRepository fallback
  -> API 요청은 NoticeService를 통해 repository 검색/조회
```

내장 크롤러 스케줄러를 켜면 다음 흐름이 추가된다.

```text
FastAPI lifespan
  -> app/crawler_scheduler.py background task 시작
  -> 기존 JSON 스냅샷을 임시 파일로 복사
  -> app/crawler/main.py가 증분 수집 후 전체 스냅샷으로 병합
  -> 결과 JSON 검증
  -> NOTICE_JSON_PATH를 os.replace()로 atomic 교체
  -> app/ingest.py가 같은 JSON을 임시 SQLite DB에 쓰고 NOTICE_DB_PATH를 atomic 교체
```

수동 스크립트 `scripts/run_incremental_crawl_publish.sh`는 JSON 스냅샷 게시를 담당한다. API 서버는 기동 시 DB가 없거나 스키마가 다르면 해당 JSON에서 DB를 다시 만든다.

## 핵심 모듈

| 파일 | 역할 |
| --- | --- |
| `app/main.py` | FastAPI 앱 생성, CORS, router 등록, crawler scheduler lifespan 연결 |
| `app/config.py` | `.env` 기반 설정. JSON/DB 경로, CORS, crawler, RAG, content enrichment 설정 |
| `app/dependencies.py` | `NoticeService`와 repository 구성. SQLite 우선, JSON fallback |
| `app/db.py` | SQLite schema version과 DDL |
| `app/ingest.py` | JSON 전체 스냅샷을 SQLite DB로 atomic ingest |
| `app/sqlite_repository.py` | SQLite 기반 공지 목록/상세/검색 repository |
| `app/repository.py` | repository protocol과 JSON fallback repository |
| `app/service.py` | API용 공지 service, pagination 정규화, 관련 공지 조회 |
| `app/chat_service.py` | `/api/chat` RAG 파이프라인, OpenAI 호출, SSE 단계 이벤트 |
| `app/classification.py` | audience/source group/category/source 필터 분류 규칙 |
| `app/search.py` | 검색어 정규화, 토큰 확장, ranking |
| `app/crawler_scheduler.py` | 서버 내장 주기 크롤링, lock, JSON publish, SQLite ingest |

## 크롤러 구조

| 경로 | 역할 |
| --- | --- |
| `app/crawler/main.py` | 전체 보드 크롤링 엔트리포인트 |
| `app/crawler/clients/` | 사이트별 HTTP client |
| `app/crawler/parsers/` | 사이트별 목록/상세 parser |
| `app/crawler/services/board_crawler.py` | client와 parser를 조합하는 보드 수집 엔진 |
| `app/crawler/services/board_registry.py` | 수집 대상 보드 레지스트리 |
| `app/crawler/services/dedup_service.py` | 기존/신규 공지 병합, 중복 제거, stale 일반공지 제거 |
| `app/crawler/services/content_enrichment_service.py` | 이미지/HWP 기반 content 보강 |
| `app/crawler/policies/notice_policy.py` | 날짜, 상시공지, 보존 정책 |

## 문서 맵

| 문서 | 내용 |
| --- | --- |
| `docs/API_SPEC.md` | API 요청/응답 계약 |
| `docs/CLASSIFICATION.md` | audience/source group/source/category 분류 기준 |
| `docs/CRAWLING_UPDATE.md` | 크롤러 publish, stale 삭제, SQLite ingest 정책 |
| `docs/RAG_PLAN.md` | `/api/chat` RAG 동작 기준 |
| `docs/DEPLOYMENT.md` | 로컬 실행, Docker Compose, Lightsail 배포 |
| `docs/ERD.md` | SQLite 실제 스키마와 JSON 원천 모델 |
| `docs/crawler/README.md` | 크롤러 세부 문서 인덱스 |

## 로컬 전용 파일

아래 파일과 디렉터리는 런타임 산출물 또는 secret이므로 커밋하지 않는다.

- `.env`, `.env.*`
- `data/*.json`, `data/*.db`
- SSH private key, `.pem`, `.key`
- 로그, pid, 로컬 HTML notes
