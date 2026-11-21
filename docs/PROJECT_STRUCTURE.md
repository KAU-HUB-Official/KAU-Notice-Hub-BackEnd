# 프로젝트 구조

## 범위

이 문서는 현재 `KAU-Notice-Hub-BackEnd` 저장소의 코드 배치와 런타임 흐름을 빠르게 파악하기 위한 구조 문서다.

백엔드는 FastAPI API 서버, 내장 KAU 공지 크롤러, SQLite 저장소, JSON 스냅샷 안전망으로 구성된다.

## 루트 구조

| 경로 | 역할 |
| --- | --- |
| `app/` | FastAPI 앱, API router, service/repository 계층, SQLite ingest, 검색/분류 로직 |
| `app/api/` | `/health`, `/api/notices`, `/api/chat`, `/api/auth/kakao`·`/api/auth/kakao/token`·`/api/me`, `/api/bookmarks` router |
| `app/crawler/` | KAU 공지 크롤러 본체. client, parser, service, policy로 분리 |
| `scripts/` | 수동 운영 스크립트. 아래 "운영 스크립트" 표 참고 |
| `scripts/research/` | 연구용 스크립트. 데이터 고정(`freeze_dataset.py`), 교차 게시 쌍 표본·판정·라벨 확정 |
| `tests/` | pytest 테스트 |
| `tests/eval/` | 분기 검증(`branch_runner.py`), RAGAS(`ragas_runner.py`), 평가 세트(`datasets/`, `ragas_cases.yml`). `docs/RAG_EVALUATION.md` 참고 |
| `docs/` | API, 배포, ERD, RAG, 평가, 마스킹, 크롤러 운영 문서 |
| `data/` | 로컬 JSON/SQLite 런타임 데이터 디렉터리. `.gitkeep`만 커밋 |
| `models/` | 이름 마스킹 NER 모델(`NAME_MODEL_DIR`). 실명 공지로 학습해 커밋하지 않고 서버에 직접 둔다 |
| `load-tests/k6/` | k6 부하 테스트 스크립트 |
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
  -> app/notice_auto_label.py가 라벨 없는 공지에 게시판 규칙 + LLM으로 대상 라벨을 붙여 NOTICE_AUTO_LABELS_PATH에 더함 (NOTICE_AUTO_LABEL_ENABLED)
  -> app/ingest.py가 같은 JSON을 임시 SQLite DB에 쓰고, 적용 대상 라벨(연구 라벨 → 자동 라벨 순)을 붙여 NOTICE_DB_PATH를 atomic 교체
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
| `app/notice_labels.py` | 공지 적용 대상 라벨 파일(`NOTICE_LABELS_PATH`) 읽기, URL 키, 목록 `target` 판정 규칙(`covers`) |
| `app/notice_auto_label.py` | 라벨 없는 새 공지의 대상 자동 라벨(게시판 규칙 + LLM), `NOTICE_AUTO_LABELS_PATH`에 기록 |
| `app/sqlite_repository.py` | SQLite 기반 공지 목록/상세/검색 repository |
| `app/repository.py` | repository protocol과 JSON fallback repository |
| `app/service.py` | API용 공지 service, pagination 정규화, 관련 공지 조회 |
| `app/service_pipeline.py` | SQLite를 쓸 수 없을 때 쓰는 메모리 기반 검색 파이프라인 |
| `app/normalize.py` | 크롤러 원본 공지를 API 공지 형태로 정리 |
| `app/privacy.py` | 공지 본문·검색 인덱스·LLM 입력에서 학번과 사람 이름 가리기 |
| `app/name_masking.py` | NER 모델(onnxruntime)로 사람 이름 찾기. 모델은 `NAME_MODEL_DIR` |
| `app/chat_service.py` | `/api/chat` RAG 파이프라인, OpenAI 호출, SSE 단계 이벤트 |
| `app/chat_log.py` | 챗봇 대화를 턴 단위로 별도 SQLite(`chat_sessions.db`)에 기록. 실패해도 응답에 영향 없음 |
| `app/rate_limit.py` | IP별 요청 횟수 제한(slowapi, 메모리). Caddy가 넣는 `X-Real-IP` 기준 |
| `app/kakao.py` | 카카오 인가 code → 토큰 교환, 사용자 정보 조회 |
| `app/auth.py` | 자체 JWT 발급·검증, 로그인 필수 의존성(`get_current_user`), 401 응답 |
| `app/user_store.py` | 사용자·북마크 SQLite(`USER_DB_PATH`) 저장소. 공지 DB와 분리 |
| `app/classification.py` | audience/source group/category/source 필터 분류 규칙 |
| `app/search.py` | 검색어 정규화, 토큰 확장, ranking |
| `app/schemas.py` | API 요청·응답 Pydantic 모델(공지, 목록, facet, 챗봇, 북마크) |
| `app/crawler_scheduler.py` | 서버 내장 주기 크롤링, lock, JSON publish, SQLite ingest |

## 운영 스크립트

| 파일 | 역할 |
| --- | --- |
| `scripts/run_incremental_crawl_publish.sh` | 수동 증분 크롤링 후 JSON 스냅샷 atomic 게시 |
| `scripts/audit_markdown_quality.py` | 공지 본문 Markdown 렌더링 깨짐 점검 |
| `scripts/audit_privacy_masking.py` | 전체 공지 마스킹 결과 점검(남은 학번, 바뀐 URL, 이름으로 가린 단어) |
| `scripts/install_name_model.py` | 이름 마스킹 모델을 SHA-256 확인 후 `NAME_MODEL_DIR`에 설치 |
| `scripts/refresh_markdown_content.py` | 옛 plain text 본문을 다시 받아 Markdown으로 재파싱 |
| `scripts/refetch_failed_enrichment.py` | 본문 보강에 실패한 공지를 다시 읽어 원문이 달라졌으면 스냅샷에 반영 |
| `scripts/fix_stray_image_notices.py` | 다른 글 이미지가 섞인 공지 본문을 패치 파일로 교체 |

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
| `docs/RAG_EVALUATION.md` | 챗봇·검색 품질 측정 방법, 평가 세트, 연구 로그 구간 |
| `docs/CROSSPOST_MERGE.md` | 교차 게시 공지 합치기 판정 기준과 기각한 접근 |
| `docs/PRIVACY_MASKING.md` | 학번·이름 마스킹 기준과 NER 모델 선택 근거 |
| `docs/AUTH_BOOKMARK_API.md` | 카카오 로그인·북마크 설계 배경, 공지 ID 변경 기록, 프론트 연동 메모 |
| `docs/GPT_API_PROMPTS.md` | GPT API 프롬프트 원문과 payload 구조 |
| `docs/DEPLOYMENT.md` | 로컬 실행, Docker Compose, Lightsail 배포 |
| `docs/ERD.md` | SQLite 실제 스키마와 JSON 원천 모델 |
| `docs/crawler/README.md` | 크롤러 세부 문서 인덱스 |

## 로컬 전용 파일

아래 파일과 디렉터리는 런타임 산출물 또는 secret이므로 커밋하지 않는다.

- `.env`, `.env.*`
- `data/*.json`, `data/*.db`
- `models/` (이름 마스킹 모델)
- SSH private key, `.pem`, `.key`
- 로그, pid, 로컬 HTML notes
