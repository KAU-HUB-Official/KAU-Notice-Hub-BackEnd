# API 명세서

## 범위
이 문서는 KAU Notice Hub FastAPI 백엔드의 현재 MVP API 계약을 정의한다.

현재 백엔드는 아래 구성을 기준으로 한다.

- FastAPI 서버
- JSON 파일 저장소
- 기존 Next.js MVP API와 호환되는 응답 shape
- Swagger UI 기반 API 명세 확인

MVP에서는 API 버전 관리, 인증, 관리자 API, 큐, 별도 검색엔진을 추가하지 않는다.

크롤러 주기 실행과 JSON 갱신 방식은 [CRAWLING_UPDATE.md](CRAWLING_UPDATE.md)를 따른다.

## 기본 URL
로컬 개발:

```text
http://localhost:8000
```

프론트엔드 환경변수:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

## API 문서 UI
FastAPI가 OpenAPI 문서를 자동 생성한다.

| URL | 용도 |
| --- | --- |
| `http://localhost:8000/docs` | Swagger UI. 브라우저에서 API 명세 확인 및 요청 테스트 |
| `http://localhost:8000/redoc` | ReDoc 문서 |
| `http://localhost:8000/openapi.json` | OpenAPI JSON |

## 공통 규칙
### 콘텐츠 타입
모든 요청/응답 본문은 JSON을 사용한다.

```http
Content-Type: application/json
```

### 필드 이름
프론트엔드 호환성을 위해 API 응답은 camelCase를 유지한다.

예:

- `audienceGroup`
- `sourceGroup`
- `sourceGroups`
- `pageSize`
- `totalPages`

### 날짜 형식
공지 날짜는 `YYYY-MM-DD` 형식을 사용한다.

```json
{
  "date": "2026-04-20"
}
```

### 필터 정규화
서버는 아래 값을 필터 없음으로 처리한다.

- 빈 문자열
- 공백만 있는 문자열
- `전체`
- `전체 출처`
- `전체 홈페이지`
- `전체 중분류`
- `전체 그룹`
- `전체 부서`
- `전체 분류`
- `__ALL_SOURCES__`
- `__ALL_DEPARTMENTS__`
- `__ALL_CATEGORIES__`
- `__ALL_AUDIENCES__`
- `__ALL_SOURCE_GROUPS__`
- `all`

지원하지 않거나 현재 대분류에서 유효하지 않은 필터는 에러로 처리하지 않고 무시한다.

### 페이지네이션 정규화
| 입력 | 동작 |
| --- | --- |
| `page` 누락 | `1` 사용 |
| 잘못된 `page` | `1` 사용 |
| `page < 1` | `1` 사용 |
| `pageSize` 누락 | `20` 사용 |
| 잘못된 `pageSize` | `20` 사용 |
| `pageSize < 1` | `1` 사용 |
| `pageSize > 100` | `100` 사용 |

### 분류 규칙
분류 기준 문서는 [CLASSIFICATION.md](CLASSIFICATION.md)다.

중요 동작:

- 크롤러 데이터의 `source_name`은 문자열 또는 배열일 수 있다.
- 정규화된 공지는 `source`와 `sources`를 모두 노출한다.
- 복수 출처 공지는 관련된 모든 source 필터에 매칭되어야 한다.
- `source` 쿼리는 아래 대분류에서만 동작한다.
  - `학부 재학생(학과/전공별)`
  - `대학원생`
  - `평생·전문교육원`
- 다른 대분류에서는 `source` 쿼리를 무시한다.
- 선택된 대분류에 중분류가 없으면 `group` 쿼리를 무시한다.
- 알 수 없는 source는 버리지 않고 `그 외`로 분류한다.

## 응답 모델
### `NoticeAttachment`
```ts
interface NoticeAttachment {
  name: string;
  url: string;
}
```

### `Notice`
```ts
interface Notice {
  id: string;
  title: string;
  content: string;
  url?: string;
  source?: string;
  sources?: string[];
  audienceGroup?: string;
  sourceGroup?: string;
  sourceGroups?: string[];
  category?: string;
  department?: string;
  date?: string;
  summary?: string;
  tags: string[];
  attachments: NoticeAttachment[];
}
```

규칙:

- `tags`는 항상 배열이다.
- `attachments`는 항상 배열이다.
- `audienceGroup`, `sourceGroup`, `sourceGroups`는 백엔드에서 계산해 붙인다.

### `NoticeFacets`
```ts
interface NoticeFacets {
  audienceGroups: string[];
  sourceGroups: string[];
  sources: string[];
  categories: string[];
  departments: string[];
}
```

facet 계산 기준:

| 필드 | 계산 범위 |
| --- | --- |
| `audienceGroups` | 전체 데이터 |
| `sourceGroups` | 대분류 필터 적용 후 |
| `sources` | 대분류/중분류 필터 적용 후, source 필터 허용 대분류에서만 |
| `categories` | 대분류/중분류 필터 적용 후 |
| `departments` | 대분류/중분류 필터 적용 후 |

### `NoticeListResult`
```ts
interface NoticeListResult {
  items: Notice[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
  facets: NoticeFacets;
}
```

### `ErrorResponse`
```ts
interface ErrorResponse {
  error: string;
  detail?: string;
}
```

MVP에서는 에러 응답을 단순하게 유지한다. 내부 상세 원인은 서버 로그에 남긴다.

## 엔드포인트
### `GET /health`
헬스 체크 API.

#### 응답 `200`
```json
{
  "status": "ok"
}
```

MVP는 `status`만 반환해도 된다.

### `GET /api/notices`
페이지네이션된 공지 목록과 필터 후보(facet)를 반환한다.

#### 쿼리 파라미터
| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `audience` | string | 아니오 | 대상자 대분류 |
| `group` | string | 아니오 | 중분류 |
| `sourceGroup` | string | 아니오 | `group` 별칭. 호환성 용도 |
| `source` | string | 아니오 | 세부 홈페이지/source 필터 |
| `q` | string | 아니오 | 검색어 |
| `category` | string | 아니오 | category 필터 |
| `department` | string | 아니오 | department 필터 |
| `page` | string/integer | 아니오 | 페이지 번호. 잘못된 값은 `1`로 보정 |
| `pageSize` | string/integer | 아니오 | 페이지 크기. 잘못된 값은 `20`으로 보정, 최대 `100` |

#### 필터 적용 순서
1. 전체 공지 로드
2. `audience` 필터 적용
3. 사용 가능한 `sourceGroups` 계산
4. 선택된 대분류에서 유효한 경우에만 `group` 필터 적용
5. `source` 필터 허용 여부 판단
6. `source`, `category`, `department`, `q` 필터 적용
7. 검색 점수화 및 정렬
8. 페이지네이션
9. 응답 항목에 분류 필드 추가

#### 정렬
`q`가 있으면:

1. 검색 점수 내림차순
2. 최신 `date` 내림차순
3. 제목 가나다순

`q`가 없으면:

1. 최신 `date` 내림차순
2. 제목 가나다순

#### 요청 예시
```http
GET /api/notices?audience=학부%20재학생(학과%2F전공별)&group=공과대&source=한국항공대학교%20컴퓨터공학과&page=1&pageSize=20
```

#### 응답 `200`
```json
{
  "items": [
    {
      "id": "notice-001",
      "title": "2026학년도 수강신청 안내",
      "content": "수강신청 기간은 ...",
      "url": "https://example.com/notice/1",
      "source": "한국항공대학교 컴퓨터공학과",
      "sources": ["한국항공대학교 컴퓨터공학과"],
      "audienceGroup": "학부 재학생(학과/전공별)",
      "sourceGroup": "AI융합대",
      "sourceGroups": ["AI융합대"],
      "category": "학사",
      "department": "교무처",
      "date": "2026-04-20",
      "summary": "수강신청 기간은 ...",
      "tags": ["학사", "한국항공대학교 컴퓨터공학과"],
      "attachments": []
    }
  ],
  "total": 1,
  "page": 1,
  "pageSize": 20,
  "totalPages": 1,
  "facets": {
    "audienceGroups": [
      "전 구성원 공통",
      "학부 재학생(학과/전공별)",
      "그 외"
    ],
    "sourceGroups": [
      "공과대",
      "AI융합대",
      "항공경영대",
      "그 외 학부"
    ],
    "sources": [
      "한국항공대학교 컴퓨터공학과"
    ],
    "categories": [
      "학사"
    ],
    "departments": [
      "교무처"
    ]
  }
}
```

#### 응답 `500`
```json
{
  "error": "공지 목록을 불러오지 못했습니다."
}
```

대표 원인:

- JSON 파일 없음
- JSON 최상위 타입이 배열이 아님
- JSON 파싱 실패 및 이전 정상 캐시 없음

### `GET /api/notices/{id}`
ID로 공지 상세를 반환한다.

#### 경로 파라미터
| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `id` | string | 예 | 공지 ID |

#### 요청 예시
```http
GET /api/notices/notice-001
```

#### 응답 `200`
```json
{
  "id": "notice-001",
  "title": "2026학년도 수강신청 안내",
  "content": "수강신청 기간은 ...",
  "url": "https://example.com/notice/1",
  "source": "한국항공대학교 공식 홈페이지",
  "sources": ["한국항공대학교 공식 홈페이지"],
  "audienceGroup": "전 구성원 공통",
  "sourceGroup": "학사",
  "sourceGroups": ["학사"],
  "category": "학사",
  "department": "교무처",
  "date": "2026-04-20",
  "summary": "수강신청 기간은 ...",
  "tags": ["학사", "한국항공대학교 공식 홈페이지"],
  "attachments": [
    {
      "name": "수강신청 안내.pdf",
      "url": "https://example.com/files/course.pdf"
    }
  ]
}
```

#### 응답 `404`
```json
{
  "error": "공지 항목을 찾을 수 없습니다."
}
```

#### 응답 `500`
```json
{
  "error": "공지 상세를 불러오지 못했습니다."
}
```

### `POST /api/chat`
공지 검색 결과를 근거로 사용자 질문에 답변한다.

MVP 기준:

- `GET /api/notices`와 같은 필터/검색 로직을 사용한다.
- 현재 구현은 local fallback 답변과 근거 목록을 반환한다.
- 벡터 검색 기반의 완전한 RAG는 아직 구현하지 않는다.

#### 요청 본문
```ts
interface ChatRequestBody {
  question: string;
  audienceGroup?: string;
  sourceGroup?: string;
  source?: string;
  category?: string;
  department?: string;
}
```

#### 요청 예시
```json
{
  "question": "공모전 정보 알려줘",
  "audienceGroup": "재학생 비교과·글로벌 프로그램",
  "sourceGroup": "국제교류"
}
```

#### 응답 모델
```ts
interface NoticeReference {
  id: string;
  title: string;
  url?: string;
  source?: string;
  date?: string;
}

interface ChatAnswer {
  answer: string;
  references: NoticeReference[];
  usedFallback: boolean;
  model: string;
}
```

#### 응답 `200`
```json
{
  "answer": "관련 공지를 찾았습니다. 자세한 내용은 아래 공지를 확인하세요.",
  "references": [
    {
      "id": "notice-101",
      "title": "국제교류 프로그램 모집 안내",
      "url": "https://example.com/notice/101",
      "source": "한국항공대학교 국제교류처",
      "date": "2026-04-22"
    }
  ],
  "usedFallback": true,
  "model": "local-fallback"
}
```

#### 응답 `400`
```json
{
  "error": "question 필드는 필수입니다."
}
```

#### 응답 `500`
```json
{
  "error": "챗봇 응답을 생성하지 못했습니다."
}
```

## CORS
MVP 로컬 개발에서는 프론트엔드 origin을 허용한다.

```text
http://localhost:3000
```

필요하면 환경변수로 허용 origin을 관리한다.

```env
BACKEND_CORS_ORIGINS=http://localhost:3000
```

## 환경변수
| 이름 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `NOTICE_JSON_PATH` | 아니오 | `./data/kau_official_posts.json` | 크롤러 JSON 파일 경로 |
| `OPENAI_API_KEY` | 아니오 | empty | 예약값. 현재 챗봇은 local fallback 사용 |
| `OPENAI_MODEL` | 아니오 | `gpt-4.1-mini` | 예약값. 현재 챗봇은 local fallback 사용 |
| `BACKEND_CORS_ORIGINS` | 아니오 | `http://localhost:3000` | 쉼표 구분 CORS origin 목록 |
| `CRAWLER_SCHEDULER_ENABLED` | 아니오 | `false` | API 프로세스 내 크롤러 스케줄러 활성화 |
| `CRAWLER_INTERVAL_SECONDS` | 아니오 | `10800` | 크롤링 주기. 기본 3시간 |
| `CRAWLER_RUN_ON_STARTUP` | 아니오 | `true` | 서버 시작 직후 1회 크롤링 |
| `CRAWLER_MAX_PAGES` | 아니오 | `0` | 게시판별 목록 페이지 상한. 0이면 최근성 정책으로 자동 중단 |
| `CRAWLER_MIN_RECORDS` | 아니오 | `1` | 게시 허용 최소 레코드 수 |
| `CRAWLER_MIN_RETAIN_RATIO` | 아니오 | `0.5` | 기존 개수 대비 급감 방어 비율 |
| `CRAWLER_LOCK_PATH` | 아니오 | empty | 크롤러 중복 실행 방지 lock 파일 경로. 미지정 시 JSON 디렉터리의 `.crawler.lock` 사용 |

## MVP 비목표
초기 백엔드 버전에서는 아래 기능을 구현하지 않는다.

- 인증
- 관리자 대시보드 API
- Alembic migration
- Redis/Celery/별도 작업 큐
- 벡터 검색
- 별도 검색엔진
- 복잡한 API 버전 관리
