# BackEnd 문서

KAU Notice Hub FastAPI 백엔드의 현재 개발, 운영, API 계약 문서 모음이다.

## 활성 문서

| 문서 | 용도 |
| --- | --- |
| [API_SPEC.md](API_SPEC.md) | `/health`, `/api/notices`, `/api/notices/{id}`, `/api/chat` 계약과 Swagger 확인 방법 |
| [CLASSIFICATION.md](CLASSIFICATION.md) | 대상자 대분류, 중분류, source 필터 분류 기준 |
| [CRAWLING_UPDATE.md](CRAWLING_UPDATE.md) | 크롤러 JSON 스냅샷 갱신과 `run_incremental_crawl_publish.sh` 사용 정책 |
| [DEPLOYMENT.md](DEPLOYMENT.md) | 로컬 실행, Docker Compose, Caddy, CORS, 배포 확인 절차 |
| [ERD.md](ERD.md) | 현재 JSON 논리 모델과 향후 PostgreSQL 전환 기준 모델 |

## 보관 문서

초기 빌드 완료 후 더 이상 일상 개발 기준으로 쓰지 않는 계획 문서는 아래에 보관한다.

| 문서 | 보관 이유 |
| --- | --- |
| [archive/initial-build/BACKEND_STRUCTURE_PLAN.md](archive/initial-build/BACKEND_STRUCTURE_PLAN.md) | 초기 구조 설계 기록 |
| [archive/initial-build/IMPLEMENTATION_PLAN.md](archive/initial-build/IMPLEMENTATION_PLAN.md) | 초기 FastAPI MVP 구현 순서와 완료 기준 기록 |

## 현재 구현 기준

- FastAPI 서버
- JSON 파일 저장소
- mtime 기반 repository 캐시
- 공지 목록/상세 API
- 로컬 fallback 챗봇 API
- 외부 스케줄러 또는 crawler container 기반 JSON 갱신
- Swagger UI 자동 제공

## 빠른 확인

서버 실행:

```bash
NOTICE_JSON_PATH=../MVP/kau_official_posts.json uvicorn app.main:app --reload --port 8000
```

확인 URL:

```text
http://localhost:8000/health
http://localhost:8000/docs
http://localhost:8000/redoc
http://localhost:8000/openapi.json
```

테스트:

```bash
pytest -q
```
