# 카카오 로그인·북마크 API 명세 (초안)

## 상태

**초안. 로그인·북마크는 아직 구현하지 않았다.** 선행 작업인 [공지 ID 변경](#공지-id-변경)만 구현했다. 구현을 마치면 이 문서의 내용을 [API_SPEC.md](API_SPEC.md)에 합치고, API_SPEC.md의 "MVP 비목표"에서 `인증`을 뺀다.

기존 API 공통 규칙(camelCase 필드, `ErrorResponse` 형식, 페이지네이션 보정, 레이트리밋)은 [API_SPEC.md](API_SPEC.md)를 그대로 따른다.

### 결정 사항

| 항목 | 결정 | 상태 |
| --- | --- | --- |
| 공지 식별자 | 공지 ID를 원문 URL 해시 기반의 고정값으로 바꾼다 ([공지 ID 변경](#공지-id-변경)) | 확정 |
| 회원 탈퇴 | `DELETE /api/me`를 포함한다 | 확정 |
| 로그인 흐름 | 프론트가 카카오 인가 code를 받고, 백엔드가 code를 토큰으로 교환해 자체 JWT를 발급한다 | 확정 |

## 전체 흐름

프론트엔드는 Next.js BFF(Vercel)가 백엔드를 서버끼리 호출하는 구조다. 브라우저는 백엔드를 직접 호출하지 않는다.

```text
[로그인]
브라우저 → 프론트: 로그인 버튼
프론트 → 브라우저: state를 쿠키에 저장하고 카카오 인가 URL로 리다이렉트
브라우저 → 카카오: 로그인·동의
카카오 → 프론트 /auth/kakao/callback?code=...&state=...
프론트(BFF): state 검증
프론트(BFF) → 백엔드 POST /api/auth/kakao { code, redirectUri }
백엔드 → 카카오: code를 카카오 토큰으로 교환, 사용자 정보 조회
백엔드: 사용자 upsert, 자체 JWT 발급
백엔드 → 프론트(BFF): { accessToken, expiresIn, user }
프론트(BFF): accessToken을 httpOnly 쿠키로 저장

[북마크]
브라우저 → 프론트(BFF): 북마크 요청 (쿠키 자동 첨부)
프론트(BFF) → 백엔드: Authorization: Bearer <accessToken>
```

- 카카오 REST API 키 외의 비밀값(client secret)과 JWT 서명 키는 백엔드에만 둔다.
- 카카오 access token은 사용자 정보를 조회하는 데만 쓰고 저장하지 않는다.
- CSRF 방지용 `state`는 인가 요청을 시작하고 콜백을 받는 프론트가 만들고 검증한다.

## 인증 규칙

### 인증 헤더

로그인이 필요한 엔드포인트는 아래 헤더를 요구한다.

```http
Authorization: Bearer <accessToken>
```

### 액세스 토큰

| 항목 | 값 |
| --- | --- |
| 형식 | JWT, HS256 서명 (`JWT_SECRET`) |
| 클레임 | `sub`(내부 사용자 ID), `iat`, `exp` |
| 만료 | 기본 14일 (`JWT_EXPIRE_SECONDS`) |
| refresh token | 없음. 만료되면 다시 카카오 로그인 |

- 서버는 세션을 저장하지 않는다. 요청마다 토큰 서명과 만료를 검증하고, `sub` 사용자가 DB에 있는지 확인한다.
- 탈퇴한 사용자의 토큰은 만료 전이라도 `401`이 된다.
- 로그아웃은 BFF가 쿠키를 지우는 것으로 처리하고, 백엔드 엔드포인트는 두지 않는다.

### 인증 실패 응답 `401`

토큰이 없거나, 형식이 틀렸거나, 서명이 맞지 않거나, 만료됐거나, 사용자가 없으면 모두 같은 응답을 준다. 어느 경우인지는 서버 로그에만 남긴다.

```http
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer
```

```json
{ "error": "로그인이 필요합니다." }
```

프론트는 `401`을 받으면 쿠키를 지우고 로그인 화면으로 보낸다.

### 시각 형식

사용자·북마크의 시각 필드는 UTC ISO 8601 문자열이다. 공지 `date`(`YYYY-MM-DD`)와는 다르다.

```json
{ "bookmarkedAt": "2026-09-19T06:30:00Z" }
```

### 레이트리밋

기존과 같이 IP 단위로 적용한다. BFF는 기존처럼 `X-Client-IP`와 `X-Internal-Token`을 함께 보낸다.

| 엔드포인트 | 기본 한도 | 환경변수 |
| --- | --- | --- |
| `POST /api/auth/kakao` | IP당 10회/분 | `RATE_LIMIT_AUTH` |
| `GET/DELETE /api/me`, `/api/bookmarks` 전체 | IP당 120회/분 | `RATE_LIMIT_BOOKMARKS` |

## 응답 모델

### `User`

```ts
interface User {
  id: string; // 내부 사용자 ID. 카카오 회원번호가 아니다.
  nickname?: string; // 카카오 프로필 닉네임. 동의하지 않았으면 없음
  profileImageUrl?: string; // 카카오 프로필 이미지. 동의하지 않았으면 없음
}
```

카카오 회원번호는 서버 DB에만 저장하고 응답에 내보내지 않는다. 이메일 등 다른 개인정보는 수집하지 않는다.

### `AuthResult`

```ts
interface AuthResult {
  accessToken: string;
  tokenType: "Bearer";
  expiresIn: number; // 초 단위
  user: User;
}
```

### `Bookmark`

```ts
interface Bookmark {
  noticeId: string;
  bookmarkedAt: string; // UTC ISO 8601
  notice: Notice | null; // 현재 공지 스냅샷에 있으면 전체 공지, 없으면 null
  saved: NoticeReference; // 북마크한 시점에 저장한 사본. 항상 있다
}
```

- `Notice`, `NoticeReference`는 [API_SPEC.md](API_SPEC.md)의 모델과 같다.
- 공지는 1년이 지나면 스냅샷에서 빠질 수 있다. 이때 `notice`는 `null`이 되지만 북마크는 지우지 않는다. 프론트는 `saved.title`과 원문 링크 `saved.url`로 "삭제된 공지" 카드를 보여준다.
- `notice`가 있으면 기존 `NoticeCard`를 그대로 쓸 수 있다.

### `BookmarkListResult`

```ts
interface BookmarkListResult {
  items: Bookmark[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
}
```

`page`, `pageSize` 보정 규칙은 `GET /api/notices`와 같다(기본 20, 최대 100).

## 엔드포인트

| 메서드 | 경로 | 인증 | 설명 |
| --- | --- | --- | --- |
| `POST` | `/api/auth/kakao` | 불필요 | 카카오 인가 code로 로그인 |
| `GET` | `/api/me` | 필요 | 내 정보 |
| `DELETE` | `/api/me` | 필요 | 회원 탈퇴 |
| `GET` | `/api/bookmarks` | 필요 | 북마크 목록 |
| `GET` | `/api/bookmarks/ids` | 필요 | 북마크한 공지 ID 전체 |
| `PUT` | `/api/bookmarks/{noticeId}` | 필요 | 북마크 추가 |
| `DELETE` | `/api/bookmarks/{noticeId}` | 필요 | 북마크 삭제 |

### `POST /api/auth/kakao`

카카오 인가 code를 받아 로그인한다. 처음 로그인하는 카카오 계정이면 사용자를 새로 만든다.

#### 요청 본문

```ts
interface KakaoLoginRequest {
  code: string; // 카카오가 콜백으로 준 인가 code
  redirectUri: string; // 인가 요청에 사용한 redirect_uri와 같은 값
}
```

- `redirectUri`는 `KAKAO_ALLOWED_REDIRECT_URIS`에 등록된 값이어야 한다. 로컬과 운영의 콜백 주소가 다르기 때문에 요청으로 받되, 허용 목록 밖이면 거부한다.
- 인가 code는 1회용이다. 같은 code로 두 번 요청하면 `401`이다.

#### 요청 예시

```http
POST /api/auth/kakao
Content-Type: application/json

{
  "code": "kakao-authorization-code",
  "redirectUri": "https://kau-notice-hub.app/auth/kakao/callback"
}
```

#### 응답 `200`

```json
{
  "accessToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "tokenType": "Bearer",
  "expiresIn": 1209600,
  "user": {
    "id": "u_7f3a9c21",
    "nickname": "항공대생",
    "profileImageUrl": "https://k.kakaocdn.net/.../profile.jpg"
  }
}
```

#### 오류 응답

| 상태 | `error` | 원인 |
| --- | --- | --- |
| `400` | `code와 redirectUri는 필수입니다.` | 필드 누락 또는 빈 문자열 |
| `400` | `허용되지 않은 redirectUri입니다.` | 허용 목록 밖의 `redirectUri` |
| `401` | `카카오 인증에 실패했습니다.` | code 만료·재사용·위조, redirect_uri 불일치 |
| `429` | `요청이 너무 많습니다. 잠시 후 다시 시도해주세요.` | 레이트리밋 |
| `502` | `카카오 서버와 통신하지 못했습니다.` | 카카오 API 타임아웃·5xx |
| `503` | `로그인을 사용할 수 없습니다.` | 서버에 카카오 키 또는 `JWT_SECRET`이 설정되지 않음 |

카카오가 돌려준 오류 코드와 메시지는 응답에 넣지 않고 서버 로그에만 남긴다.

### `GET /api/me`

토큰 주인의 정보를 반환한다. 프론트가 헤더에 로그인 상태를 표시할 때 쓴다.

#### 응답 `200`

```json
{
  "id": "u_7f3a9c21",
  "nickname": "항공대생",
  "profileImageUrl": "https://k.kakaocdn.net/.../profile.jpg"
}
```

#### 오류 응답

`401`

### `DELETE /api/me`

회원 탈퇴. 사용자와 그 사용자의 북마크를 모두 삭제한다.

- 삭제 후 기존 토큰은 `401`이 된다.
- 같은 카카오 계정으로 다시 로그인하면 빈 북마크의 새 사용자로 만든다.
- 카카오 쪽 앱 연결 끊기(unlink)는 이번 범위에 넣지 않는다. 사용자는 카카오 계정 설정에서 직접 연결을 끊을 수 있다.

#### 응답 `204`

본문 없음.

#### 오류 응답

`401`

### `GET /api/bookmarks`

내 북마크 목록을 최근에 북마크한 순서로 반환한다.

#### 쿼리 파라미터

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `page` | string/integer | 아니오 | 페이지 번호. 잘못된 값은 `1`로 보정 |
| `pageSize` | string/integer | 아니오 | 페이지 크기. 잘못된 값은 `20`으로 보정, 최대 `100` |

#### 응답 `200`

```json
{
  "items": [
    {
      "noticeId": "a3f9c2e81b7d4056",
      "bookmarkedAt": "2026-09-19T06:30:00Z",
      "notice": {
        "id": "a3f9c2e81b7d4056",
        "title": "2026학년도 2학기 수강신청 안내",
        "content": "수강신청 기간은 ...",
        "url": "https://kau.ac.kr/...",
        "source": "한국항공대학교 공식 홈페이지",
        "sources": ["한국항공대학교 공식 홈페이지"],
        "audienceGroup": "전 구성원 공통",
        "sourceGroup": "학사",
        "sourceGroups": ["학사"],
        "category": "학사",
        "date": "2026-08-20",
        "tags": ["학사"],
        "attachments": []
      },
      "saved": {
        "id": "a3f9c2e81b7d4056",
        "title": "2026학년도 2학기 수강신청 안내",
        "url": "https://kau.ac.kr/...",
        "source": "한국항공대학교 공식 홈페이지",
        "date": "2026-08-20"
      }
    },
    {
      "noticeId": "5d10be7f02c94a8e",
      "bookmarkedAt": "2025-09-02T01:12:00Z",
      "notice": null,
      "saved": {
        "id": "5d10be7f02c94a8e",
        "title": "2025학년도 국가장학금 2차 신청 안내",
        "url": "https://kau.ac.kr/...",
        "source": "한국항공대학교 공식 홈페이지",
        "date": "2025-08-28"
      }
    }
  ],
  "total": 2,
  "page": 1,
  "pageSize": 20,
  "totalPages": 1
}
```

#### 오류 응답

| 상태 | `error` |
| --- | --- |
| `401` | `로그인이 필요합니다.` |
| `429` | `요청이 너무 많습니다. 잠시 후 다시 시도해주세요.` |
| `500` | `북마크 목록을 불러오지 못했습니다.` |

### `GET /api/bookmarks/ids`

내가 북마크한 공지 ID 전체를 반환한다. 공지 목록·상세 화면에서 북마크 아이콘을 채울지 판단하는 데 쓴다.

기존 `GET /api/notices` 응답에 북마크 여부를 섞지 않기 위해 따로 둔다. 사용자당 북마크 수에 상한(`BOOKMARK_MAX_PER_USER`)이 있어 응답 크기가 제한된다.

#### 응답 `200`

```json
{
  "noticeIds": ["a3f9c2e81b7d4056", "5d10be7f02c94a8e"]
}
```

#### 오류 응답

`401`, `429`, `500`

### `PUT /api/bookmarks/{noticeId}`

공지를 북마크한다. 이미 북마크한 공지면 아무것도 바꾸지 않고 기존 북마크를 반환한다(멱등).

#### 경로 파라미터

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `noticeId` | string | 예 | 공지 ID |

#### 요청 본문

없음.

#### 응답

| 상태 | 의미 | 본문 |
| --- | --- | --- |
| `201` | 새로 북마크함 | `Bookmark` |
| `200` | 이미 북마크돼 있음 | `Bookmark` (기존 `bookmarkedAt` 유지) |

#### 오류 응답

| 상태 | `error` | 원인 |
| --- | --- | --- |
| `401` | `로그인이 필요합니다.` | 인증 실패 |
| `404` | `공지 항목을 찾을 수 없습니다.` | 현재 공지 스냅샷에 없는 ID. 새 북마크만 해당하고, 이미 북마크한 공지는 스냅샷에서 빠졌어도 `200` |
| `409` | `북마크는 최대 500개까지 저장할 수 있습니다.` | 상한 초과. 숫자는 `BOOKMARK_MAX_PER_USER` |
| `429` | `요청이 너무 많습니다. 잠시 후 다시 시도해주세요.` | 레이트리밋 |
| `500` | `북마크를 저장하지 못했습니다.` | 저장 실패 |

### `DELETE /api/bookmarks/{noticeId}`

북마크를 삭제한다. 북마크하지 않은 공지여도 성공으로 처리한다(멱등).

#### 응답 `204`

본문 없음.

#### 오류 응답

| 상태 | `error` |
| --- | --- |
| `401` | `로그인이 필요합니다.` |
| `429` | `요청이 너무 많습니다. 잠시 후 다시 시도해주세요.` |
| `500` | `북마크를 삭제하지 못했습니다.` |

## 공지 ID 변경

**구현 완료, 배포 전.** 확정된 ID 규칙은 [API_SPEC.md](API_SPEC.md)의 `Notice` 규칙에 반영했다.

북마크와 공지 상세 링크가 크롤링 뒤에도 같은 공지를 가리키도록 공지 ID 생성 방식을 바꾼다. `GET /api/notices`, `GET /api/notices/{id}`, 챗봇 `references`의 `id`에 모두 적용되는 API 계약 변경이다.

### 이전 방식의 문제

크롤러 JSON에는 `id` 필드가 없다. 그래서 `app/normalize.py`가 `제목-날짜-출처-배열순번`을 slug로 만들어 ID로 썼다.

- 제목이 짧으면 ID에 배열 순번이 들어간다. 새 공지가 추가되거나 오래된 공지가 지워져 순서가 밀리면 ID가 바뀐다.
- 제목이 길면 48자에서 잘려 순번이 빠지는 대신, 앞부분이 같은 공지끼리 `-2`, `-3`이 순서대로 붙는다.
- 프론트 `sitemap.ts`가 `/notices/{id}`를 검색엔진에 제출하므로, ID가 바뀌면 색인된 주소가 404가 되거나 다른 공지를 보여준다.

### 새 규칙

| 조건 | ID |
| --- | --- |
| 원문 URL이 있음 | 정규화한 원문 URL의 SHA-256 앞 16자리 hex |
| 원문 URL이 없음 | `제목`, `날짜`, `출처`를 이은 문자열의 SHA-256 앞 16자리 hex (배열 순번 제외) |
| 위 결과가 겹침 | 기존과 같이 뒤에 `-2`, `-3`을 붙인다 |

- URL 정규화는 크롤러 중복 제거와 같은 함수(`canonicalize_original_url`, `app/crawler/services/url_normalizer.py`)를 쓴다.
- 원문 URL이 같으면 크롤링을 몇 번 반복하거나 공지 순서가 바뀌어도 ID가 같다. 제목이 수정돼도 ID는 그대로다.
- 한 ID가 다른 공지를 가리키는 일은 없다. 다른 공지는 원문 URL이 다르므로 ID도 다르다.
- 클라이언트는 ID를 형식 없는 문자열로 다룬다. 길이나 형식에 의존하지 않는다.

### ID가 바뀌는 경우

아래 경우에는 같은 공지의 ID가 바뀌어 옛 주소가 404가 된다. 다른 공지를 보여주지는 않는다.

- 학교 사이트가 공지 URL을 바꿨을 때. 예: 2026-09 학과 사이트 도메인 이전(`ai.kau.ac.kr:8100` → `com.kau.ac.kr` 등)
- `canonicalize_original_url`의 정규화 규칙을 바꿨을 때. 규칙을 고치면 해당 사이트 공지의 ID가 모두 바뀌므로, 고칠 때 북마크·공유 링크 영향을 함께 검토한다.
- 교차 게시 병합으로 대표 원문 URL이 바뀌었을 때
- 원문 URL이 없는 공지의 제목·날짜·출처가 바뀌었을 때

### 영향

- 프론트 코드 수정은 필요 없다. 프론트는 ID를 `encodeURIComponent`로 URL에 넣기만 한다.
- 공지 자체는 그대로 남는다. 사이트 안의 목록·검색·상세·챗봇 링크는 새 ID로 바로 만들어진다.
- 배포 직후 사이트 밖에 남은 기존 ID 주소(검색엔진 색인, 공유 링크, 브라우저 즐겨찾기)는 한 번 404가 된다. 기존 ID는 크롤링마다 바뀌거나 다른 공지를 가리킬 수 있던 값이라, 옛 주소를 새 주소로 연결하는 처리는 두지 않는다.
- 배포 직후 Google Search Console에 사이트맵을 다시 제출하면 새 주소가 빨리 색인된다.
- 북마크 기능보다 먼저, 또는 같이 배포한다. 그러면 옛 ID로 저장된 북마크가 없어서 북마크 데이터를 옮길 필요가 없다.

## 저장소

사용자와 북마크는 공지 DB와 분리한 SQLite 파일(`USER_DB_PATH`, 기본 `./data/users.db`)에 저장한다. 공지 DB(`NOTICE_DB_PATH`)는 크롤링 때마다 통째로 교체되기 때문이다. 기존 챗봇 로그 DB(`CHAT_LOG_DB_PATH`)와 같은 방식이다. 테이블 설계는 구현 시 [ERD.md](ERD.md)에 적는다.

## 환경변수

| 이름 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `KAKAO_REST_API_KEY` | 로그인 사용 시 | empty | 카카오 앱 REST API 키 |
| `KAKAO_CLIENT_SECRET` | 아니오 | empty | 카카오 콘솔에서 Client Secret을 켰을 때만 설정 |
| `KAKAO_ALLOWED_REDIRECT_URIS` | 로그인 사용 시 | empty | 허용할 `redirectUri` 목록. 쉼표 구분. 카카오 콘솔에 등록한 Redirect URI와 같아야 한다 |
| `JWT_SECRET` | 로그인 사용 시 | empty | JWT 서명 키. 32바이트 이상 랜덤 값(`openssl rand -hex 32`) |
| `JWT_EXPIRE_SECONDS` | 아니오 | `1209600` | 액세스 토큰 유효 시간. 기본 14일 |
| `USER_DB_PATH` | 아니오 | `./data/users.db` | 사용자·북마크 SQLite 파일 |
| `BOOKMARK_MAX_PER_USER` | 아니오 | `500` | 사용자당 북마크 상한 |
| `RATE_LIMIT_AUTH` | 아니오 | `10/minute` | `POST /api/auth/kakao` IP당 한도 |
| `RATE_LIMIT_BOOKMARKS` | 아니오 | `120/minute` | `/api/me`, `/api/bookmarks` IP당 한도 |

`KAKAO_REST_API_KEY`, `KAKAO_ALLOWED_REDIRECT_URIS`, `JWT_SECRET` 중 하나라도 비어 있으면 `POST /api/auth/kakao`는 `503`을 반환한다. 이 경우에도 공지·챗봇 API는 그대로 동작한다.

## 프론트엔드 연동 메모

프론트 저장소에서 할 작업이다. 백엔드 범위는 아니지만 계약을 맞추기 위해 적어 둔다.

- **로그인 시작**: `https://kauth.kakao.com/oauth/authorize?client_id={REST_API_KEY}&redirect_uri={콜백 주소}&response_type=code&state={랜덤값}`으로 보낸다. `state`는 httpOnly 쿠키에도 저장한다.
- **콜백 페이지** `/auth/kakao/callback`: 쿼리의 `state`와 쿠키의 값이 다르면 중단한다. 같으면 BFF가 `POST /api/auth/kakao`를 호출한다.
- **토큰 보관**: `accessToken`은 `httpOnly; Secure; SameSite=Lax` 쿠키에 `expiresIn`만큼 저장한다. 브라우저 JS와 localStorage에는 두지 않는다.
- **API 호출**: BFF route가 쿠키의 토큰을 꺼내 `Authorization: Bearer`로 붙인다.
- **401 처리**: 쿠키를 지우고 로그인을 다시 안내한다.
- **개인정보 처리방침** `/privacy`: 카카오 회원번호, 닉네임, 프로필 이미지 수집과 탈퇴 시 삭제를 반영한다.
