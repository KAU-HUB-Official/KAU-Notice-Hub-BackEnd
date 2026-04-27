# ERD

## 범위
이 문서는 KAU Notice Hub 독립 백엔드의 데이터 모델을 정의한다.

초기 MVP 백엔드는 단순하게 시작한다.

- 실행 저장소는 크롤러가 생성한 JSON 파일로 시작한다.
- 서비스 코드는 추후 PostgreSQL 저장소로 교체할 수 있도록 경계를 둔다.
- 저장소가 JSON에서 DB로 바뀌어도 프론트엔드 API 계약은 바꾸지 않는다.

따라서 이 ERD는 **향후 PostgreSQL 저장소의 기준 모델**이며, MVP JSON 저장소는 같은 논리 모델로 메모리에서 정규화해 사용한다.

## 핵심 개념
| 개념 | 설명 |
| --- | --- |
| 공지 | 사용자에게 노출되는 정규화된 공지 데이터 |
| 공지 출처 | 한 공지가 속한 원본 홈페이지. 한 공지가 여러 출처를 가질 수 있음 |
| 분류 | `CLASSIFICATION.md` 기준으로 계산되는 대상자 대분류/중분류 |
| 첨부파일 | 원본 공지에 연결된 파일 |

## 분류 필드
분류 기준은 [CLASSIFICATION.md](CLASSIFICATION.md)를 따른다.

| 필드 | 의미 | MVP JSON 저장 여부 | PostgreSQL 저장 여부 |
| --- | --- | --- | --- |
| `audienceGroup` | 대상자 대분류 | 요청 시점 계산 | 선택적 캐시 컬럼/테이블 |
| `sourceGroup` | 대표 중분류 | 요청 시점 계산 | 선택적 캐시 컬럼/테이블 |
| `sourceGroups` | 매칭된 전체 중분류 | 요청 시점 계산 | 선택적 캐시 테이블 |
| `source` | 대표 출처 홈페이지 | 원천 데이터에서 정규화 | 저장 |
| `sources` | 전체 출처 홈페이지 목록 | 원천 데이터에서 정규화 | 저장 |

초기 MVP에서 분류값은 수동 편집 데이터가 아니라, 항상 결정적 함수로 계산한다.

## Mermaid ERD
```mermaid
erDiagram
  notices ||--o{ notice_sources : has
  notices ||--o{ notice_attachments : has
  notices ||--o{ notice_classifications : classified_as

  notices {
    varchar id PK
    text title
    text content
    text summary
    text url
    varchar category
    varchar department
    date published_at
    timestamptz crawled_at
    text searchable_text
    timestamptz created_at
    timestamptz updated_at
  }

  notice_sources {
    bigint id PK
    varchar notice_id FK
    varchar source_name
    integer source_order
    timestamptz created_at
  }

  notice_classifications {
    bigint id PK
    varchar notice_id FK
    varchar audience_group
    varchar source_group
    timestamptz created_at
  }

  notice_attachments {
    bigint id PK
    varchar notice_id FK
    text name
    text url
    integer attachment_order
    timestamptz created_at
  }
```

## 테이블
### `notices`
정규화된 공지 1건을 저장한다.

| 컬럼 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `id` | `varchar` | 예 | 안정적인 공지 ID. 크롤러가 제공하지 않으면 제목/날짜/출처 기반으로 생성하고 중복을 보정한다. |
| `title` | `text` | 예 | 공지 제목. fallback: `제목 없음 공지 N`. |
| `content` | `text` | 예 | 공지 본문. fallback: `본문 정보가 비어 있습니다.` |
| `summary` | `text` | 아니오 | 요약. 없으면 본문에서 생성한다. |
| `url` | `text` | 아니오 | 원문 공지 URL. |
| `category` | `varchar` | 아니오 | `category`, `category_raw`, `type` 중 첫 번째 정규화 값. |
| `department` | `varchar` | 아니오 | 부서/기관명. |
| `published_at` | `date` | 아니오 | `date`, `published_at`, `created_at`, `updated_at`에서 정규화한 게시일. |
| `crawled_at` | `timestamptz` | 아니오 | 크롤러 수집 시각. |
| `searchable_text` | `text` | 아니오 | 단순 검색용 사전 계산 텍스트. |
| `created_at` | `timestamptz` | 예 | DB 행 생성 시각. |
| `updated_at` | `timestamptz` | 예 | DB 행 수정 시각. |

권장 인덱스:

```sql
CREATE INDEX idx_notices_published_at ON notices (published_at DESC);
CREATE INDEX idx_notices_category ON notices (category);
CREATE INDEX idx_notices_department ON notices (department);
```

MVP 검색은 메모리 문자열 매칭 또는 `ILIKE` 수준으로 충분하다. PostgreSQL trigram 인덱스는 실제 성능 문제가 생긴 뒤 추가한다.

### `notice_sources`
공지별 전체 출처 홈페이지를 저장한다.

| 컬럼 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `id` | `bigint` | 예 | 대체 기본키. |
| `notice_id` | `varchar` | 예 | `notices.id` FK. |
| `source_name` | `varchar` | 예 | 정규화된 출처 홈페이지 이름. |
| `source_order` | `integer` | 예 | `0`이면 대표 출처. |
| `created_at` | `timestamptz` | 예 | DB 행 생성 시각. |

규칙:

- 원천 `source_name`은 문자열 또는 배열일 수 있다.
- 첫 번째 정규화 source는 API의 `Notice.source`가 된다.
- 전체 정규화 source는 API의 `Notice.sources`가 된다.
- source 필터는 대표 출처만 보지 않고 모든 출처를 대상으로 매칭해야 한다.

권장 인덱스:

```sql
CREATE INDEX idx_notice_sources_notice_id ON notice_sources (notice_id);
CREATE INDEX idx_notice_sources_source_name ON notice_sources (source_name);
CREATE UNIQUE INDEX uq_notice_sources_notice_source
  ON notice_sources (notice_id, source_name);
```

### `notice_classifications`
PostgreSQL 저장소 도입 시 분류 결과를 캐시한다.

| 컬럼 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `id` | `bigint` | 예 | 대체 기본키. |
| `notice_id` | `varchar` | 예 | `notices.id` FK. |
| `audience_group` | `varchar` | 예 | 대상자 대분류. 예: `전 구성원 공통`. |
| `source_group` | `varchar` | 아니오 | 중분류. 중분류가 없는 대분류에서는 null 가능. |
| `created_at` | `timestamptz` | 예 | DB 행 생성 시각. |

규칙:

- MVP JSON 구현에서는 이 값을 요청 시점에 계산한다.
- PostgreSQL에서는 필터/facet 성능을 위해 캐시할 수 있다.
- 한 공지가 여러 중분류에 매칭되면 여러 row를 저장한다.
- 중분류가 없는 대분류는 `source_group = null` 행을 하나 저장하는 방식을 권장한다.

권장 인덱스:

```sql
CREATE INDEX idx_notice_classifications_notice_id
  ON notice_classifications (notice_id);

CREATE INDEX idx_notice_classifications_audience_group
  ON notice_classifications (audience_group);

CREATE INDEX idx_notice_classifications_audience_source_group
  ON notice_classifications (audience_group, source_group);
```

### `notice_attachments`
공지 첨부파일을 저장한다.

| 컬럼 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `id` | `bigint` | 예 | 대체 기본키. |
| `notice_id` | `varchar` | 예 | `notices.id` FK. |
| `name` | `text` | 예 | 첨부파일 표시명. fallback: `첨부파일`. |
| `url` | `text` | 예 | 첨부파일 URL. |
| `attachment_order` | `integer` | 예 | 원본 순서. |
| `created_at` | `timestamptz` | 예 | DB 행 생성 시각. |

권장 인덱스:

```sql
CREATE INDEX idx_notice_attachments_notice_id
  ON notice_attachments (notice_id);

CREATE UNIQUE INDEX uq_notice_attachments_notice_url
  ON notice_attachments (notice_id, url);
```

## API 논리 모델
DB 모델은 프론트엔드가 사용하는 `Notice` 객체로 변환된다.

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

매핑:

| API 필드 | 출처 |
| --- | --- |
| `id` | `notices.id` |
| `title` | `notices.title` |
| `content` | `notices.content` |
| `url` | `notices.url` |
| `source` | `source_order = 0`인 `notice_sources.source_name` |
| `sources` | `source_order` 순서의 전체 `notice_sources.source_name` |
| `audienceGroup` | 요청 시점 계산값 또는 `notice_classifications.audience_group` |
| `sourceGroup` | 분류 순서상 첫 번째 중분류 |
| `sourceGroups` | 분류 순서상 전체 중분류 |
| `category` | `notices.category` |
| `department` | `notices.department` |
| `date` | `notices.published_at`의 `YYYY-MM-DD` 문자열 |
| `summary` | `notices.summary` |
| `tags` | MVP에서는 category와 sources에서 파생 |
| `attachments` | `notice_attachments` 행 목록 |

## MVP JSON 형태
크롤러 JSON은 초기 저장 포맷으로 유지할 수 있다.

백엔드 서버가 실행 중이어도 크롤러는 별도 주기 작업으로 실행할 수 있다. 크롤러 결과 파일 갱신, atomic 교체, 백엔드 캐시 재로드 정책은 [CRAWLING_UPDATE.md](CRAWLING_UPDATE.md)를 따른다.

권장 원천 레코드:

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

복수 출처 예시:

```json
{
  "title": "복수 홈페이지에 노출된 공지",
  "source_name": [
    "한국항공대학교 컴퓨터공학과",
    "한국항공대학교 소프트웨어학과"
  ],
  "category_raw": ["공지", "학사"]
}
```

## 향후 PostgreSQL 전환 경로
1. MVP 서비스 API는 저장소 인터페이스 기반으로 유지한다.
2. `JsonNoticeRepository`를 먼저 구현한다.
3. 이후 SQLAlchemy/Alembic을 추가하되 API 응답 모델은 변경하지 않는다.
4. 크롤러 JSON을 관계형 테이블에 upsert(삽입/갱신)하는 가져오기 모듈을 추가한다.
5. 분류 규칙이 안정화된 뒤 `notice_classifications` 캐시를 사용한다.

초기 백엔드 버전은 PostgreSQL 없이 실행 가능해야 한다.

## 향후 사용자/맞춤형 공지/키워드 알림 확장
로그인, 회원가입, 맞춤형 공지, 키워드 알림은 MVP 공지 탐색 기능이 안정화된 뒤 별도 사용자 도메인으로 확장한다.

중요한 원칙:

- `notices` 계열 테이블은 공지 원본/출처/분류/첨부파일만 담당한다.
- 사용자 선호, 읽음, 북마크, 알림 상태는 `users` 계열 테이블에서 관리한다.
- 맞춤형 공지를 위해 공지 데이터를 사용자별로 복사하지 않는다.
- 기존 공지 목록 조회 로직 위에 사용자 선호 조건을 추가로 적용한다.
- 알림 기능은 키워드 매칭과 발송 이력을 분리해 중복 발송을 막는다.
- 초기 MVP에는 포함하지 않고, PostgreSQL 도입 이후 확장하는 것을 권장한다.

### 확장 ERD 초안
```mermaid
erDiagram
  users ||--o{ user_notice_preferences : has
  users ||--o{ user_keyword_alerts : has
  users ||--o{ user_notice_reads : reads
  users ||--o{ user_notice_bookmarks : bookmarks
  users ||--o{ notification_channels : owns
  users ||--o{ notification_logs : receives

  notices ||--o{ user_notice_reads : read_by
  notices ||--o{ user_notice_bookmarks : bookmarked_by
  notices ||--o{ notification_logs : notified_for

  users {
    bigint id PK
    varchar email
    varchar password_hash
    varchar name
    boolean is_active
    timestamptz created_at
    timestamptz updated_at
  }

  user_notice_preferences {
    bigint id PK
    bigint user_id FK
    varchar audience_group
    varchar source_group
    varchar source_name
    varchar category
    varchar department
    boolean enabled
    timestamptz created_at
    timestamptz updated_at
  }

  user_keyword_alerts {
    bigint id PK
    bigint user_id FK
    varchar keyword
    boolean enabled
    timestamptz created_at
    timestamptz updated_at
  }

  user_notice_reads {
    bigint user_id FK
    varchar notice_id FK
    timestamptz read_at
  }

  user_notice_bookmarks {
    bigint user_id FK
    varchar notice_id FK
    timestamptz created_at
  }

  notification_channels {
    bigint id PK
    bigint user_id FK
    varchar channel_type
    varchar target
    boolean enabled
    timestamptz created_at
    timestamptz updated_at
  }

  notification_logs {
    bigint id PK
    bigint user_id FK
    varchar notice_id FK
    bigint keyword_alert_id FK
    varchar channel_type
    varchar status
    timestamptz sent_at
    timestamptz created_at
  }
```

### 확장 테이블 설명
| 테이블 | 역할 |
| --- | --- |
| `users` | 로그인/회원가입 사용자 계정 |
| `user_notice_preferences` | 대상자 대분류, 중분류, 출처, category, department 기반 맞춤형 공지 조건 |
| `user_keyword_alerts` | 사용자가 등록한 키워드 알림 조건 |
| `user_notice_reads` | 사용자별 공지 읽음 상태 |
| `user_notice_bookmarks` | 사용자별 공지 북마크 |
| `notification_channels` | 이메일, 푸시 등 알림 수신 채널 |
| `notification_logs` | 공지별/키워드별 알림 발송 이력 |

### 맞춤형 공지 처리 흐름
맞춤형 공지는 별도 공지 테이블을 만들지 않고, 기존 공지 조회 결과에 사용자 조건을 적용한다.

```text
전체 공지 조회
  -> 기존 audience/group/source/q 필터 적용
  -> 사용자 선호 조건 적용
  -> 읽음/북마크/키워드 매칭 여부 추가
  -> 개인화 목록 반환
```

예상 API:

```text
GET  /api/me/notices/recommended
PUT  /api/me/preferences
POST /api/me/notices/{id}/read
POST /api/me/notices/{id}/bookmark
DELETE /api/me/notices/{id}/bookmark
```

### 키워드 알림 처리 흐름
키워드 알림은 공지 수집 또는 정규화 이후에 실행한다.

```text
신규/갱신 공지 저장
  -> 활성화된 user_keyword_alerts 조회
  -> 공지 title/summary/content/source/category에서 키워드 매칭
  -> notification_logs 중복 여부 확인
  -> 알림 발송 또는 발송 대기 기록
```

예상 API:

```text
GET    /api/me/keyword-alerts
POST   /api/me/keyword-alerts
PATCH  /api/me/keyword-alerts/{id}
DELETE /api/me/keyword-alerts/{id}
```

초기에는 실제 이메일/푸시 발송 없이 “키워드에 매칭된 공지 목록”만 제공할 수 있다. 이후 알림 채널이 정해지면 `notification_channels`와 `notification_logs`를 사용해 발송 기능을 추가한다.
