# API 명세서

## 범위

이 문서는 KAU Notice Hub FastAPI 백엔드의 현재 API 계약을 정의한다.

현재 백엔드는 아래 구성을 기준으로 한다.

- FastAPI 서버
- SQLite DB(`NOTICE_DB_PATH`) 우선 저장소
- JSON 전체 스냅샷(`NOTICE_JSON_PATH`) 안전망과 부트스트랩 원천
- 기존 Next.js MVP API와 호환되는 응답 shape
- Swagger UI 기반 API 명세 확인

현재 범위에서는 API 버전 관리, 인증, 관리자 API, 큐, 별도 검색엔진을 추가하지 않는다.

크롤러 주기 실행, JSON 게시, SQLite ingest 방식은 [CRAWLING_UPDATE.md](CRAWLING_UPDATE.md)를 따른다.

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

| URL                                  | 용도                                                  |
| ------------------------------------ | ----------------------------------------------------- |
| `http://localhost:8000/docs`         | Swagger UI. 브라우저에서 API 명세 확인 및 요청 테스트 |
| `http://localhost:8000/redoc`        | ReDoc 문서                                            |
| `http://localhost:8000/openapi.json` | OpenAPI JSON                                          |

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

| 입력              | 동작       |
| ----------------- | ---------- |
| `page` 누락       | `1` 사용   |
| 잘못된 `page`     | `1` 사용   |
| `page < 1`        | `1` 사용   |
| `pageSize` 누락   | `20` 사용  |
| 잘못된 `pageSize` | `20` 사용  |
| `pageSize < 1`    | `1` 사용   |
| `pageSize > 100`  | `100` 사용 |

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

| 필드             | 계산 범위                                                 |
| ---------------- | --------------------------------------------------------- |
| `audienceGroups` | 전체 데이터                                               |
| `sourceGroups`   | 대분류 필터 적용 후                                       |
| `sources`        | 대분류/중분류 필터 적용 후, source 필터 허용 대분류에서만 |
| `categories`     | 대분류/중분류 필터 적용 후                                |
| `departments`    | 대분류/중분류 필터 적용 후                                |

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

| 이름          | 타입           | 필수   | 설명                                               |
| ------------- | -------------- | ------ | -------------------------------------------------- |
| `audience`    | string         | 아니오 | 대상자 대분류                                      |
| `group`       | string         | 아니오 | 중분류                                             |
| `sourceGroup` | string         | 아니오 | `group` 별칭. 호환성 용도                          |
| `source`      | string         | 아니오 | 세부 홈페이지/source 필터                          |
| `q`           | string         | 아니오 | 검색어                                             |
| `category`    | string         | 아니오 | category 필터                                      |
| `department`  | string         | 아니오 | department 필터                                    |
| `page`        | string/integer | 아니오 | 페이지 번호. 잘못된 값은 `1`로 보정                |
| `pageSize`    | string/integer | 아니오 | 페이지 크기. 잘못된 값은 `20`으로 보정, 최대 `100` |

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

#### 검색어 매칭

`q`는 다음 순서로 시도하며, 하나라도 통과하면 결과에 포함된다.

1. 정규화한 `q` 전체가 검색 텍스트에 부분 문자열로 포함
2. 공백/구두점을 제거한 `q`가 동일하게 정규화한 검색 텍스트에 포함 (띄어쓰기 변종 흡수)
3. 토큰별 매칭. 토큰은 stop word(`알려줘`, `최신`, `안내` 등)와 1글자 한글을 제거한 결과이며, 토큰 개수가 2개 이상이면 최소 2개가 매칭되어야 한다.

#### 정렬

`q`가 있으면:

1. 검색 점수 내림차순. 점수는 토큰별 매칭 위치 가중치(title 7, summary 4, tags 3, source/category 2, content 1)에 최신성 보정을 합산한다.

### Notice.content 포맷

`content` 필드는 **Markdown(CommonMark + GFM 표) 문자열**이다. 프론트엔드는 Markdown renderer(react-markdown, marked 등)로 그려야 한다.

- 헤딩: `# ## ### ...`
- 목록: `-`, `1.`
- 표: GFM 표 (`| 헤더 | 헤더 |` 형태)
- 링크: `[text](url)` — 상대 경로는 크롤링 시 절대 URL로 치환됨
- 이미지: `![alt](url)` — 동일하게 절대 URL 보장
- 본문이 비어 있는 공지는 `**[이미지 본문]**`, `**[동영상 본문]**`, `**[첨부파일 공지]**` 같은 fallback 헤더로 시작한다. 마이그레이션 이전 데이터에는 `[이미지 본문] ...`처럼 bold 없는 plain text 형태가 남아 있을 수 있고, 둘 다 Markdown으로 안전하게 렌더된다.

   - 7일 이내 `+5`, 30일 이내 `+3`, 90일 이내 `+1`, 365일 초과 `-2`
   - 매칭 점수가 0인 공지에는 최신성 보정을 적용하지 않는다.
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
    "audienceGroups": ["전 구성원 공통", "학부 재학생(학과/전공별)", "그 외"],
    "sourceGroups": ["공과대", "AI융합대", "항공경영대", "그 외 학부"],
    "sources": ["한국항공대학교 컴퓨터공학과"],
    "categories": ["학사"],
    "departments": ["교무처"]
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

- SQLite DB 조회 실패
- SQLite DB 부트스트랩에 필요한 JSON 파일 없음
- JSON 최상위 타입이 배열이 아님
- JSON 파싱 실패 및 이전 정상 캐시 없음

### `GET /api/notices/{id}`

ID로 공지 상세를 반환한다.

#### 경로 파라미터

| 이름 | 타입   | 필수 | 설명    |
| ---- | ------ | ---- | ------- |
| `id` | string | 예   | 공지 ID |

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

- `GET /api/notices`와 같은 키워드 검색/필터로 관련 공지를 찾는다.
- `RAG_ENABLED=true`이고 `OPENAI_API_KEY`가 설정돼 있으면 OpenAI Responses API로 답변을 생성한다 (`usedFallback=false`, `model=OPENAI_MODEL`).
- `RAG_QUERY_EXTRACTION_ENABLED=true`(기본)이면 검색 직전 분기(triage) LLM이 `search`/`history`/`out_of_domain`을 정하고, `search`면 질문에서 명사 키워드를 뽑아 검색어로 쓴다. 분기가 실패하면 질문 원문을 그대로 검색한다.
- `history` 분기: 이전 대화가 쌓인 상태에서 직전 답변을 재가공하는 후속 질문("더 짧게", "두 번째 거 제목 뭐였지")이면 새 검색 없이 history만으로 답한다. 이때 `references`는 빈 배열이다. 이전 대화가 없으면 이 분기는 쓰지 않고 검색으로 강등한다.
- `out_of_domain` 분기: 질문을 공지 도메인 밖으로 판정하면 검색을 skip하고 "KAU 공지 안내만 도와드릴 수 있어요" 안내를 `usedFallback=true`로 돌려준다. SSE에서는 `search_completed`의 `references`가 빈 배열이고 `answer_completed`에 안내 문구가 들어간다. 단 `history`가 비어 있지 않으면 도메인 외로 단정하지 않고 질문 원문으로 검색을 시도한다.
- 검색은 `RAG_CANDIDATE_POOL`(기본 15)개 후보를 가져온 뒤, 후보가 `RAG_MAX_REFERENCES`보다 많으면 rerank LLM이 제목·게시일만 보고 관련 공지를 최종 n개로 좁힌다. 후보가 n개 이하면 rerank를 생략한다.
- 키워드 기반 검색이 0건이거나 rerank가 관련 공지 없음(빈 배열)으로 판정하면 무관한 최신 공지로 채우지 않고 빈 `references`와 fallback 답변을 반환한다.
- 비활성화/키 부재/호출 실패 시 local fallback 답변을 반환한다 (`usedFallback=true`, `model="local-fallback"`).
- 벡터 검색 기반 RAG는 아직 구현하지 않는다. 자세한 동작과 환경변수는 [RAG_PLAN.md](RAG_PLAN.md)를 참고한다.
- UI에서 단계별 진행("공지 검색중 → 검색 완료 → 답변 생성")을 그려야 하면 아래 `POST /api/chat/stream` SSE 엔드포인트를 사용한다.
- 후속 질문 맥락을 유지하려면 요청 본문의 `history` 필드(`ChatMessage[]`)에 이전 대화를 함께 전달한다. 서버는 최근 10개 메시지까지만 사용하고 각 메시지는 500자에서 잘라 LLM 프롬프트에 포함시킨다. history는 데이터로만 취급되며 시스템 지시 변경에 사용되지 않는다.
- 답변 LLM에는 서버 기준 오늘 날짜가 시스템 프롬프트로 주입된다. 사용자가 "지금", "현재", "이번주", "신청 가능" 같은 시간 한정 표현을 쓰면 LLM이 각 공지 본문의 마감일을 오늘 기준으로 비교해 마감이 지난 공지를 답에서 제외하고, 마감 정보가 불분명하면 "마감 정보 확인 필요"라고 안내한다.

### `POST /api/chat/stream`

`POST /api/chat`과 동일한 입력을 받아 Server-Sent Events(SSE)로 단계별 결과를 스트리밍한다. 응답 `Content-Type`은 `text/event-stream`이며 각 줄은 `data: {...}\n\n` 형식의 JSON이다.

#### 이벤트 타입

| `type`             | 시점                        | 추가 필드                                               |
| ------------------ | --------------------------- | ------------------------------------------------------- |
| `search_started`   | 검색 시작 직전              | 없음                                                    |
| `search_completed` | references가 결정된 직후    | `references: NoticeReference[]`                         |
| `answer_completed` | LLM 답변 또는 fallback 완료 | `answer: string`, `usedFallback: bool`, `model: string` |
| `error`            | 처리 중 예외 발생           | `error: string`                                         |

이벤트 순서는 정상 흐름에서 `search_started` → `search_completed` → `answer_completed`다. 실패 시 마지막에 `error` 이벤트가 추가될 수 있다.

#### 요청 본문

`POST /api/chat`과 동일한 `ChatRequestBody`.

#### 응답 예시

```text
data: {"type": "search_started"}

data: {"type": "search_completed", "references": [{"id": "...", "title": "...", "url": "...", "source": "...", "date": "..."}]}

data: {"type": "answer_completed", "answer": "...", "usedFallback": false, "model": "gpt-4.1-mini"}
```

검색 결과가 0건이거나 RAG가 비활성/실패면 `answer_completed`의 `usedFallback`이 `true`, `model`이 `"local-fallback"`이고 `answer`는 local fallback 메시지다.

#### 요청 본문

```ts
interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface ChatRequestBody {
  question: string;
  history?: ChatMessage[]; // 선택. 최근 대화 turn (default [])
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

| 이름                                       | 필수   | 기본값                           | 설명                                                                                 |
| ------------------------------------------ | ------ | -------------------------------- | ------------------------------------------------------------------------------------ |
| `NOTICE_JSON_PATH`                         | 아니오 | `./data/kau_official_posts.json` | 크롤러 JSON 파일 경로                                                                |
| `NOTICE_DB_PATH`                           | 아니오 | `./data/kau_notice_hub.db`       | API가 우선 읽는 SQLite DB 경로                                                       |
| `OPENAI_API_KEY`                           | 아니오 | empty                            | content 보강과 RAG 챗봇 OpenAI 호출에 사용. 없으면 챗봇은 local fallback             |
| `OPENAI_MODEL`                             | 아니오 | `gpt-4.1-mini`                   | RAG 챗봇과 content 보강 OpenAI 호출 기본 모델                                        |
| `RAG_ENABLED`                              | 아니오 | `false`                          | `true`이고 API key가 있으면 `/api/chat`이 OpenAI 답변 생성                           |
| `RAG_MAX_REFERENCES`                       | 아니오 | `6`                              | rerank 후 응답 references 최대 수(최종 n)                                            |
| `RAG_CANDIDATE_POOL`                       | 아니오 | `15`                             | rerank 전에 가져올 후보 공지 수. n 이하면 rerank 생략                                |
| `RAG_QUERY_EXTRACTION_ENABLED`             | 아니오 | `true`                           | RAG 활성화 시 검색 전 분기(triage) LLM 사용                                          |
| `CONTENT_ENRICHMENT_ENABLED`               | 아니오 | `false`                          | 이미지/HWP 기반 content 보강 활성화                                                  |
| `CONTENT_ENRICHMENT_PROVIDER`              | 아니오 | `openai`                         | content 보강 provider                                                                |
| `CONTENT_ENRICHMENT_MODEL`                 | 아니오 | `gpt-4.1-mini`                   | content 보강 기본 모델                                                               |
| `CONTENT_ENRICHMENT_FALLBACK_MODEL`        | 아니오 | `gpt-5.5`                        | 이미지 텍스트 부족 시 재시도 모델                                                    |
| `CONTENT_ENRICHMENT_IMAGE_DETAIL`          | 아니오 | `high`                           | 이미지 입력 detail 값                                                                |
| `CONTENT_ENRICHMENT_MIN_TEXT_LENGTH`       | 아니오 | `30`                             | 보강 후보 판단 최소 본문 길이                                                        |
| `CONTENT_ENRICHMENT_MAX_ASSETS_PER_NOTICE` | 아니오 | `3`                              | 공지 1건당 처리할 최대 asset 수                                                      |
| `CONTENT_ENRICHMENT_MAX_FILE_BYTES`        | 아니오 | `10485760`                       | 다운로드할 asset 최대 크기                                                           |
| `CONTENT_ENRICHMENT_MAX_CALLS_PER_RUN`     | 아니오 | `50`                             | crawl 1회당 보강 API 호출 상한                                                       |
| `CONTENT_ENRICHMENT_ALLOWED_DOMAINS`       | 아니오 | KAU 관련 도메인 목록             | asset 다운로드 허용 도메인 allowlist                                                 |
| `BACKEND_CORS_ORIGINS`                     | 아니오 | `http://localhost:3000`          | 쉼표 구분 CORS origin 목록                                                           |
| `CRAWLER_SCHEDULER_ENABLED`                | 아니오 | `false`                          | API 프로세스 내 크롤러 스케줄러 활성화                                               |
| `CRAWLER_INTERVAL_SECONDS`                 | 아니오 | `10800`                          | 크롤링 주기. 기본 3시간                                                              |
| `CRAWLER_RUN_ON_STARTUP`                   | 아니오 | `true`                           | 서버 시작 직후 1회 크롤링                                                            |
| `CRAWLER_MAX_PAGES`                        | 아니오 | `0`                              | 게시판별 목록 페이지 상한. 0이면 최근성 정책으로 자동 중단                           |
| `CRAWLER_MIN_RECORDS`                      | 아니오 | `1`                              | 게시 허용 최소 레코드 수                                                             |
| `CRAWLER_MIN_RETAIN_RATIO`                 | 아니오 | `0.5`                            | 기존 개수 대비 급감 방어 비율                                                        |
| `CRAWLER_LOCK_PATH`                        | 아니오 | empty                            | 크롤러 중복 실행 방지 lock 파일 경로. 미지정 시 JSON 디렉터리의 `.crawler.lock` 사용 |

## MVP 비목표

초기 백엔드 버전에서는 아래 기능을 구현하지 않는다.

- 인증
- 관리자 대시보드 API
- Alembic migration
- Redis/Celery/별도 작업 큐
- 벡터 검색
- 별도 검색엔진
- 복잡한 API 버전 관리
