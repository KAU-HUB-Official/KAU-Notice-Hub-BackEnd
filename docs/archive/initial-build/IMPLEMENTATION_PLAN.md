# 구현 계획

## 범위
이 문서는 KAU Notice Hub 독립 백엔드의 MVP 구현 순서와 완료 기준을 정의한다.

목표:

- 현재 Next.js MVP의 API 동작을 FastAPI 백엔드로 분리한다.
- 초기 저장소는 JSON 파일로 유지한다.
- 프론트엔드 API 계약을 깨지 않는다.
- 분류/검색/필터링 로직을 백엔드로 이동한다.

관련 문서:

- [ERD.md](../../ERD.md)
- [API_SPEC.md](../../API_SPEC.md)
- [CRAWLING_UPDATE.md](../../CRAWLING_UPDATE.md)
- [DEPLOYMENT.md](../../DEPLOYMENT.md)

## MVP 구현 원칙
- 단순한 파일 구조로 시작한다.
- API 서버와 크롤러 실행 책임을 분리한다.
- JSON 저장소를 먼저 구현하되 repository 경계를 둔다.
- 분류 규칙은 `MVP/docs/CLASSIFICATION.md`와 동일하게 맞춘다.
- 검색은 벡터 검색 없이 규칙 기반 텍스트 검색으로 구현한다.
- 구현이 복잡해질 때만 모듈을 추가 분리한다.

## 권장 초기 디렉토리 구조
```text
BackEnd
├── app
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── schemas.py
│   ├── classification.py
│   ├── normalize.py
│   ├── search.py
│   ├── repository.py
│   ├── service.py
│   └── api
│       ├── __init__.py
│       ├── health.py
│       ├── notices.py
│       └── chat.py
├── data
│   └── .gitkeep
├── scripts
│   └── run_incremental_crawl_publish.sh
├── tests
├── docs
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

초기에는 `domain/`, `services/`, `repositories/`처럼 깊게 나누지 않는다. 코드가 커지면 그때 분리한다.

## 단계별 구현
### 1단계: FastAPI 기본 골격
작업:

- `pyproject.toml` 작성
- FastAPI, Uvicorn, Pydantic 의존성 추가
- `app/main.py` 생성
- router 등록 구조 생성
- `/health` 구현
- `.env.example` 작성

완료 기준:

- `uvicorn app.main:app --reload --port 8000`으로 서버가 실행된다.
- `GET /health`가 `{"status":"ok"}`를 반환한다.
- Swagger 문서(`/docs`)가 열린다.

### 2단계: 스키마 정의
작업:

- `schemas.py`에 API 응답 모델 정의
- `NoticeAttachment`
- `Notice`
- `NoticeFacets`
- `NoticeListResult`
- `NoticeReference`
- `ChatRequestBody`
- `ChatAnswer`
- `ErrorResponse`

완료 기준:

- [API_SPEC.md](../../API_SPEC.md)의 응답 shape과 필드명이 일치한다.
- API 응답은 camelCase를 유지한다.
- `tags`, `attachments`는 항상 배열로 내려간다.

### 3단계: 원천 JSON 정규화
작업:

- `normalize.py` 구현
- 유연한 필드 매핑 지원
- HTML 제거 및 summary 생성
- 날짜 정규화
- 첨부파일 정규화
- `source_name` 문자열/배열 처리
- `source`, `sources` 보존
- id 누락 시 fallback id 생성
- id 중복 시 suffix 부여

필드 매핑:

| API 필드 | 원천 후보 |
| --- | --- |
| `title` | `title`, `subject`, `name` |
| `content` | `content`, `body`, `text`, `description` |
| `source/sources` | `source`, `source_name`, `source_type`, `board` |
| `category` | `category`, `category_raw`, `type` |
| `department` | `department`, `department_name`, `office` |
| `url` | `url`, `original_url`, `link`, `href` |
| `date` | `date`, `published_at`, `created_at`, `updated_at` |
| `id` | `id`, `notice_id`, `post_id`, `uuid` |

완료 기준:

- 기존 MVP JSON을 읽어 `Notice` 배열로 정규화할 수 있다.
- `source_name` 배열이 `sources`로 보존된다.
- 본문만 있는 공지는 목록용 `summary`가 생성된다.

### 4단계: JSON Repository
작업:

- `repository.py`에 저장소 인터페이스 작성
- `JsonNoticeRepository` 구현
- `NOTICE_JSON_PATH` 환경변수 사용
- 파일 `mtime` 기반 캐시 구현
- JSON root array 검증
- 정규화 성공 시 캐시 교체
- 정규화 실패 시 이전 정상 캐시 유지 검토

권장 인터페이스:

```python
class NoticeRepository:
    async def list_all(self) -> list[Notice]:
        ...

    async def get_by_id(self, notice_id: str) -> Notice | None:
        ...
```

완료 기준:

- `NOTICE_JSON_PATH`의 JSON을 읽어 전체 공지 목록을 반환한다.
- 파일 변경 전에는 캐시를 사용한다.
- 파일 변경 후 다음 요청에서 재로드된다.

### 5단계: 분류 로직 이식
작업:

- `classification.py` 구현
- `MVP/src/lib/notices.ts`의 분류 상수/규칙을 Python으로 이식
- `AUDIENCE_GROUP_ORDER`
- `SOURCE_GROUP_ORDER`
- `classify_notice_audience`
- `classify_notice_source_groups`
- `classify_notice_source_group`
- `should_use_source_filter`
- `get_notice_source_names`
- filter value 정규화

완료 기준:

- `MVP/docs/CLASSIFICATION.md`의 주요 source별 기대 대분류/중분류와 일치한다.
- source 필터 허용 대분류는 아래 3개뿐이다.
  - `학부 재학생(학과/전공별)`
  - `대학원생`
  - `평생·전문교육원`
- 알 수 없는 source는 `그 외`로 분류된다.

### 6단계: 검색 로직 구현
작업:

- `search.py` 구현
- 검색어 공백 정리
- 불용어 제거
- title/summary/content/source/sources/category/department/tags 검색
- 분류값도 검색 대상에 포함
- relevance score 계산
- 검색어가 없으면 최신순 정렬

완료 기준:

- 기존 MVP의 규칙 기반 검색 동작과 유사하게 동작한다.
- `공모전 정보 알려줘` 같은 자연어 검색이 불용어 때문에 0건으로 쉽게 떨어지지 않는다.
- 검색어가 있으면 관련도 우선, 동률이면 최신순으로 정렬된다.

### 7단계: Notice Service
작업:

- `service.py` 구현
- API query 정규화
- 필터 적용 순서 구현
- facet 계산 구현
- 페이지네이션 구현
- 응답 item enrich 구현

필터 순서:

```text
1. 전체 공지 로드
2. audience 필터 적용
3. sourceGroups facet 계산
4. 유효한 group만 적용
5. source 필터 허용 여부 판단
6. source/category/department/q 필터 적용
7. 검색 점수화 및 정렬
8. 페이지네이션
9. audienceGroup/sourceGroup/sourceGroups enrich
```

완료 기준:

- [API_SPEC.md](../../API_SPEC.md)의 `GET /api/notices` 동작과 일치한다.
- 지원하지 않는 `source` 또는 `group` query는 에러가 아니라 무시된다.
- `page`, `pageSize` 보정이 동작한다.

### 8단계: Notice API
작업:

- `app/api/notices.py` 구현
- `GET /api/notices`
- `GET /api/notices/{id}`
- query parameter parsing
- 에러 응답 처리

완료 기준:

- 기존 프론트가 기대하는 응답 shape으로 목록을 받을 수 있다.
- 상세 API도 분류 필드가 enrich된 공지를 반환한다.
- 없는 ID는 404를 반환한다.

### 9단계: Chat API
작업:

- `app/api/chat.py` 구현
- `POST /api/chat`
- 질문 필수 검증
- NoticeService 검색 결과를 references로 변환
- `OPENAI_API_KEY`가 없으면 local fallback 응답
- OpenAI 연동은 선택 구현

완료 기준:

- API key 없이도 fallback 응답이 동작한다.
- references는 실제 검색 결과 기반이다.
- chat 검색도 목록 API와 같은 필터 규칙을 사용한다.

### 10단계: 크롤링 갱신 스크립트
작업:

- `scripts/run_incremental_crawl_publish.sh` 초안 작성
- 최종 JSON을 작업 파일로 복사
- 크롤러를 작업 파일 대상으로 실행
- JSON 검증
- 성공 시 최종 파일 atomic 교체
- 실패 시 기존 파일 유지

완료 기준:

- API 서버가 실행 중이어도 JSON 파일이 깨진 상태로 노출되지 않는다.
- 증분 수집 결과가 기존 전체 스냅샷과 병합된다.
- 최신 파일 교체 후 API가 다음 요청에서 변경을 감지한다.

상세 정책은 [CRAWLING_UPDATE.md](../../CRAWLING_UPDATE.md)를 따른다.

### 11단계: Docker 배포 파일
작업:

- `Dockerfile`
- `docker-compose.yml`
- `.dockerignore`
- Caddy 또는 Nginx reverse proxy 예시
- volume 설정

완료 기준:

- `docker compose up -d --build`로 API 서버가 뜬다.
- `/data/kau_official_posts.json`을 volume으로 공유할 수 있다.
- `/health`와 `/api/notices`가 container 환경에서 동작한다.

상세 정책은 [DEPLOYMENT.md](../../DEPLOYMENT.md)를 따른다.

### 12단계: 프론트 연결 전환
작업:

- 프론트 repo에서 API base URL 환경변수 추가
- `NEXT_PUBLIC_API_BASE_URL` 기반 fetch로 변경
- Next.js 내부 `/api/notices` route handler 의존 제거 또는 proxy로 임시 유지
- 프론트에서 기존 화면 동작 확인

완료 기준:

- 프론트가 FastAPI 백엔드 API를 호출한다.
- audience/group/source/q/page 상태 동기화가 유지된다.
- 기존 UI 컴포넌트의 대규모 수정 없이 동작한다.

프론트 배포 상세는 [MVP/docs/DEPLOYMENT.md](../../../../MVP/docs/DEPLOYMENT.md)를 따른다.

## 테스트 계획
### 단위 테스트
필수 테스트:

- `source_name` 문자열 정규화
- `source_name` 배열 정규화
- 중복 ID suffix 처리
- 공식 홈페이지 분류
- 학과/학부 source의 단과대 중분류
- 대학원/평생교육원 source 필터 허용
- 알 수 없는 source의 `그 외` fallback
- source 필터 미지원 대분류에서 source query 무시
- group이 없는 대분류에서 group query 무시
- page/pageSize 보정

### API 테스트
필수 테스트:

- `GET /health`
- `GET /api/notices` 기본 응답 shape
- `GET /api/notices?audience=...`
- `GET /api/notices?group=...`
- `GET /api/notices?source=...`
- `GET /api/notices?q=...`
- `GET /api/notices/{id}`
- 없는 ID 404
- `POST /api/chat` fallback 응답

### 크롤링 갱신 테스트
필수 테스트:

- tmp JSON 검증 성공 시 최종 파일 교체
- tmp JSON 파싱 실패 시 기존 파일 유지
- 레코드 수 급감 시 교체 보류 가능
- 파일 mtime 변경 후 repository 재로드

## MVP 완료 기준
아래 조건을 만족하면 백엔드 MVP 구현 완료로 본다.

- FastAPI 서버가 독립 실행된다.
- JSON 파일 기반으로 공지 목록/상세 API가 동작한다.
- `CLASSIFICATION.md` 기준 분류가 API 응답에 반영된다.
- 기존 프론트 API 계약이 유지된다.
- 챗봇 fallback 응답이 동작한다.
- 크롤러 결과 JSON 갱신 후 API가 최신 데이터를 반영한다.
- Docker Compose로 배포 가능한 상태다.
- 최소 테스트가 통과한다.
