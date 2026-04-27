# 백엔드 구조 설계 계획

## 목적
크롤러가 만든 공지 JSON을 `docs/CLASSIFICATION.md`의 대상자 대분류, 중분류, 세부 홈페이지 체계로 정규화한 뒤 프론트엔드가 바로 탐색할 수 있는 API를 제공한다.

핵심 목표는 아래와 같다.

- 크롤러 원천 데이터와 프론트 응답 모델을 분리한다.
- `source_name` 단일값/배열을 모두 보존해 여러 홈페이지에 동시에 걸리는 공지를 지원한다.
- 분류 규칙은 API, 검색, 챗봇이 같은 기준을 쓰도록 단일 도메인 계층에서 관리한다.
- MVP 단계에서는 JSON 파일 저장소를 유지하되, 동일한 서비스 인터페이스로 DB 전환이 가능하게 둔다.

## 현재 전제
현재 MVP 백엔드는 Next.js Route Handler 기반이다.

| 역할 | 현재 파일 |
| --- | --- |
| 입력 JSON 로드 | `src/server/notices/json-notice-repository.ts` |
| 원천 데이터 정규화 | `src/server/notices/normalize-notice.ts` |
| 분류/검색/필터 유틸 | `src/lib/notices.ts` |
| 목록/상세 서비스 | `src/server/notices/notice-service.ts` |
| 목록 API | `src/app/api/notices/route.ts` |
| 상세 API | `src/app/api/notices/[id]/route.ts` |
| 챗봇 검색 연결 | `src/server/ai/chat-service.ts` |

입력 데이터는 `NOTICE_JSON_PATH` 환경변수로 지정하며, 기본값은 `kau_official_posts.json`이다.

## 전체 파이프라인
```text
Crawler JSON
  -> RawNotice Reader
  -> Normalizer
  -> Classification Enricher
  -> Repository / Index
  -> NoticeService
  -> /api/notices, /api/notices/[id], /api/chat
  -> Frontend Notice Explorer
```

1. 크롤러는 `title`, `content`, `source_name`, `category_raw`, `published_at`, `original_url`, `attachments` 중심의 원천 데이터를 만든다.
2. 백엔드는 원천 필드를 `Notice` 모델로 정규화한다.
3. 정규화 과정에서 `source`는 대표 출처, `sources`는 전체 출처 배열로 보존한다.
4. 분류 계층은 `sources`, `category`, `title`을 기준으로 `audienceGroup`, `sourceGroup`, `sourceGroups`를 계산한다.
5. 서비스 계층은 query param을 검증하고, 분류 체계에 맞게 필터와 facet을 계산한다.
6. API는 프론트가 필요한 `items`, `facets`, `pagination`을 반환한다.

## 권장 백엔드 모듈 구조
현재 파일을 한 번에 크게 옮기기보다, 기능 경계를 아래처럼 정리하는 방향으로 확장한다.

```text
src/server/notices
├── domain
│   ├── notice-types.ts
│   ├── notice-classification.ts
│   ├── notice-filter.ts
│   └── notice-search.ts
├── ingestion
│   ├── raw-notice-reader.ts
│   ├── normalize-notice.ts
│   ├── validate-raw-notice.ts
│   └── enrich-classification.ts
├── repositories
│   ├── notice-repository.ts
│   ├── json-notice-repository.ts
│   └── db-notice-repository.ts
├── services
│   ├── notice-query-service.ts
│   ├── notice-detail-service.ts
│   └── notice-facet-service.ts
└── api
    ├── parse-notice-query.ts
    └── notice-response-presenter.ts
```

MVP에서는 기존 `src/lib/notices.ts`를 공유 분류 모듈로 유지해도 된다. 다만 백엔드 책임이 커지면 `domain/notice-classification.ts`로 옮기고, 프론트는 해당 상수와 label helper만 import하는 구조가 더 명확하다.

## 도메인 모델
프론트 응답의 기준 모델은 `Notice`다.

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

분류 필드는 저장 필드라기보다 파생 필드로 취급한다.

- `audienceGroup`: 대분류
- `sourceGroup`: 대표 중분류
- `sourceGroups`: 복수 출처 공지가 여러 중분류에 걸릴 때 쓰는 중분류 배열
- `source`: 대표 홈페이지
- `sources`: 모든 홈페이지 배열

JSON MVP에서는 요청 시점에 파생 필드를 계산한다. DB 전환 시에는 조회 성능을 위해 `notice_classifications` 또는 materialized column으로 저장할 수 있다.

## 분류 계층 설계
분류 계층은 `CLASSIFICATION.md`의 규칙을 코드로 표현하는 단일 진입점을 가진다.

필수 함수:

```ts
classifyNoticeAudience(notice): string
classifyNoticeSourceGroups(notice): string[]
classifyNoticeSourceGroup(notice): string | undefined
shouldUseSourceFilter(audienceGroup): boolean
getNoticeSourceNames(notice): string[]
```

분류 순서:

1. `source_name` 또는 `sources`를 정규화한다.
2. 특정 source 키워드를 기준으로 대분류를 결정한다.
3. 대분류별 규칙으로 중분류를 계산한다.
4. 세부 홈페이지 필터가 필요한 대분류에서만 `source` 필터를 허용한다.

주의할 점:

- `source_name`이 배열이면 모든 값을 `sources`로 보존한다.
- 복수 source 공지는 source facet에 모든 홈페이지가 노출되어야 한다.
- `학부 재학생(학과/전공별)`, `대학원생`, `평생·전문교육원` 외 대분류에서는 `source` query를 무시한다.
- 중분류가 없는 대분류에서는 `group` query를 무시한다.
- 알 수 없는 source는 무조건 버리지 않고 `그 외`로 분류해 누락을 막는다.

## 저장소 설계
### MVP: JSON 저장소
현재 구조를 유지한다.

```text
JsonNoticeRepository
  - NOTICE_JSON_PATH 파일 stat 확인
  - mtime 기반 메모리 캐시
  - JSON 배열 파싱
  - normalizeNotice 실행
  - id 중복 시 suffix 부여
```

장점:

- 크롤러 결과물을 바로 교체할 수 있다.
- DB 없이 배포와 테스트가 단순하다.
- 분류 규칙 수정 후 재기동 없이 요청 시점 계산으로 반영 가능하다.

보완할 점:

- 크롤러가 결과 파일을 쓰는 동안 API가 읽지 않도록 atomic write가 필요하다.
- JSON 파싱 실패 시 마지막 정상 캐시를 유지하는 fallback 정책을 둘 수 있다.
- `그 외` 비율, 빈 title/content, 잘못된 URL 같은 데이터 품질 지표를 로그로 남긴다.

### 확장: DB 저장소
데이터가 커지거나 운영 이력이 필요해지면 `NoticeRepository` 구현만 교체한다.

권장 테이블:

```text
notices
  id
  title
  content
  summary
  url
  category
  department
  published_at
  crawled_at
  searchable_text

notice_sources
  notice_id
  source_name
  source_order

notice_source_groups
  notice_id
  audience_group
  source_group

notice_attachments
  notice_id
  name
  url
```

DB에서도 API 응답 인터페이스는 바꾸지 않는다. 프론트는 저장소가 JSON인지 DB인지 몰라야 한다.

## 서비스 계층 설계
`NoticeService`는 프론트 탐색 흐름과 같은 순서로 필터를 적용한다.

1. 전체 목록 로드
2. 대분류 필터 적용
3. 대분류 내에서 사용 가능한 중분류 facet 계산
4. 유효한 중분류일 때만 중분류 필터 적용
5. 세부 홈페이지 필터 허용 여부 계산
6. source/category/department/q 필터 적용
7. 검색어가 있으면 점수화, 없으면 최신순 정렬
8. 페이지네이션
9. item에 분류 파생 필드 enrich

목록 API 응답:

```ts
interface NoticeListResult {
  items: Notice[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
  facets: {
    audienceGroups: string[];
    sourceGroups: string[];
    sources: string[];
    categories: string[];
    departments: string[];
  };
}
```

facet 계산 기준:

- `audienceGroups`: 전체 데이터 기준
- `sourceGroups`: 선택된 대분류 기준
- `sources`: 선택된 대분류와 중분류 기준, source 필터 허용 대분류에서만 반환
- `categories`, `departments`: 선택된 대분류와 중분류 기준

## API 계약
### `GET /api/notices`
프론트 목록 화면의 주 API다.

```text
GET /api/notices?audience=...&group=...&source=...&q=...&page=1&pageSize=20
```

쿼리 파라미터:

| 이름 | 의미 |
| --- | --- |
| `audience` | 대상자 대분류 |
| `group` | 중분류 |
| `source` | 세부 홈페이지 |
| `q` | 검색어 |
| `page` | 페이지 번호 |
| `pageSize` | 페이지 크기, 최대 100 |

서버 검증 규칙:

- `page < 1`이면 1로 보정한다.
- `pageSize`는 1~100 범위로 보정한다.
- 현재 대분류에 없는 `group`은 무시한다.
- source 필터 미지원 대분류의 `source`는 무시한다.
- 빈 값, `전체`, `__ALL_*__` 토큰은 필터 없음으로 처리한다.

### `GET /api/notices/[id]`
상세 화면의 API다. 반환 전 `audienceGroup`, `sourceGroup`, `sourceGroups`를 enrich한다.

### `POST /api/chat`
챗봇도 같은 필터 규칙을 사용한다.

```json
{
  "question": "공모전 정보 알려줘",
  "audienceGroup": "재학생 비교과·글로벌 프로그램",
  "sourceGroup": "국제교류"
}
```

챗봇은 `NoticeService.findRelevantNotices`를 통해 필터가 적용된 범위에서 근거 공지를 찾는다.

## 크롤러 산출물 연동 규칙
크롤러는 백엔드가 안정적으로 정규화할 수 있도록 아래 필드를 최대한 채운다.

```json
{
  "id": "optional-stable-id",
  "title": "공지 제목",
  "content": "공지 본문",
  "source_name": "한국항공대학교 공식 홈페이지",
  "source_type": "kau_official",
  "category_raw": "학사",
  "department": "교무처",
  "published_at": "2026-04-20",
  "original_url": "https://example.com/notice/1",
  "attachments": []
}
```

중복 병합으로 한 공지가 여러 홈페이지에 속하면 아래처럼 배열을 허용한다.

```json
{
  "source_name": [
    "한국항공대학교 컴퓨터공학과",
    "한국항공대학교 소프트웨어학과"
  ],
  "category_raw": ["공지", "학사"]
}
```

백엔드는 첫 source를 대표값으로 쓰되, 전체 배열을 `sources`로 보존한다.

## 검색/정렬 설계
MVP 검색은 규칙 기반 텍스트 검색이다.

검색 대상:

- 제목
- 요약
- 본문
- 대분류
- 중분류
- 대표 source
- 전체 sources
- category
- department
- tags

정렬 기준:

1. 검색어가 있으면 relevance score 내림차순
2. 점수가 같거나 검색어가 없으면 `date` 최신순
3. 날짜가 같으면 제목 가나다순

검색 고도화가 필요하면 현재 서비스 인터페이스를 유지한 채 `notice-search.ts` 내부를 하이브리드 검색 또는 벡터 검색으로 교체한다.

## 에러와 운영 정책
권장 에러 정책:

- JSON 파일 없음: 500 반환, 운영 로그에 파일 경로 기록
- JSON 형식 오류: 500 반환, 마지막 정상 캐시가 있으면 fallback 사용 검토
- 레코드 일부 필드 누락: 해당 레코드는 가능한 기본값으로 정규화
- 원문 URL 없음: 상세 연결은 숨기되 목록에서는 노출 가능
- 분류 실패: `그 외`로 분류하고 source 이름을 로그 샘플링

운영 지표:

- 전체 공지 수
- 대분류별 공지 수
- `그 외` 비율
- source facet 개수
- JSON 로드 시간
- 검색 응답 시간
- 크롤러 산출물 마지막 갱신 시각

## 테스트 계획
### 분류 테스트
`CLASSIFICATION.md`의 표를 fixture로 만들어 source별 기대 대분류/중분류를 검증한다.

필수 케이스:

- 공식 홈페이지 category/title 기준 `일반`, `학사`, `장학/대출`, `입찰`, `행사`
- 학과/학부 source의 단과대 중분류
- `source_name` 배열의 복수 source facet
- 대학원생과 평생·전문교육원의 중분류 없음
- source 필터 허용 대분류 3개
- 알 수 없는 source의 `그 외` fallback

### 서비스 테스트
목록 API 서비스는 필터 순서를 검증한다.

- 대분류 변경 시 중분류/source 선택이 무효화되는 효과
- 현재 대분류에 없는 group 무시
- source 필터 미지원 대분류에서 source query 무시
- page/pageSize 보정
- 검색어 점수 정렬

### 계약 테스트
프론트가 의존하는 응답 shape을 고정한다.

- `items`는 항상 배열
- `facets.sources`는 source 필터 미지원 대분류에서 빈 배열
- 각 item은 `tags`, `attachments` 배열을 항상 포함
- 상세 API도 목록 item과 같은 분류 필드를 포함

## 단계별 구현 계획
### 1단계: MVP 구조 안정화
- 기존 JSON 저장소를 유지한다.
- `normalize-notice.ts`, `notice-service.ts`, `src/lib/notices.ts`에 분산된 책임을 문서화한다.
- 분류 fixture 테스트를 추가한다.
- 크롤러 결과 저장 시 atomic write 정책을 적용한다.

### 2단계: 도메인 모듈 분리
- `src/lib/notices.ts`에서 분류, 필터, 검색 함수를 파일 단위로 분리한다.
- 프론트는 UI 상수와 label helper만 import한다.
- 백엔드는 분류/검색 도메인 함수를 직접 사용한다.

### 3단계: 색인 계층 추가
- JSON 로드 후 `audienceGroup`, `sourceGroups`, `searchableText`, `dateTimestamp`를 미리 계산한 in-memory index를 만든다.
- 요청마다 반복되는 분류 계산을 줄인다.
- 캐시는 파일 `mtimeMs`가 바뀔 때만 재생성한다.

### 4단계: DB 전환 준비
- `NoticeRepository` 인터페이스를 목록 조회, 상세 조회, facet 조회 기준으로 확장한다.
- `JsonNoticeRepository`와 `DbNoticeRepository`가 같은 `NoticeService`를 사용하게 한다.
- 크롤러 산출물을 DB upsert하는 ingestion job을 추가한다.

## 최종 기준
백엔드 구조가 완료되었다고 판단하는 기준은 아래와 같다.

- 프론트는 `audience`, `group`, `source`, `q`, `page`, `pageSize`만으로 전체 탐색을 수행한다.
- API 응답의 facet은 `CLASSIFICATION.md`의 노출 규칙과 일치한다.
- 크롤러가 source를 추가해도 분류 규칙만 갱신하면 UI 구조가 깨지지 않는다.
- JSON 저장소에서 DB 저장소로 바꿔도 API 계약은 유지된다.
- 챗봇과 목록 검색이 같은 분류/필터 규칙을 공유한다.
