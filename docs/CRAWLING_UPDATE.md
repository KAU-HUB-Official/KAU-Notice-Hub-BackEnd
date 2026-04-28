# 주기 크롤링 및 공지 데이터 갱신

## 범위
이 문서는 백엔드 서버가 실행 중인 동안 크롤러를 주기적으로 실행하고, 최신 공지 데이터를 API에 반영하는 방식을 정의한다.

현재 MVP에서는 구조를 복잡하게 만들지 않는다.

- FastAPI 서버는 공지 조회 API를 안정적으로 제공한다.
- 크롤러 코드는 `app/crawler`에 포함하고, 실행은 별도 프로세스 또는 별도 컨테이너에서 주기 실행한다.
- 크롤러 결과는 JSON 파일로 저장한다.
- 백엔드는 JSON 파일 변경을 감지해 최신 데이터를 다시 읽는다.
- Redis, Celery, 별도 queue, 복잡한 worker는 MVP에서 사용하지 않는다.

## 현재 MVP 구조
```text
Scheduler(cron/systemd/Docker scheduler)
  -> app/crawler 실행
  -> 기존 스냅샷 기준 증분 수집
  -> 기존 데이터와 신규/수정 데이터 병합
  -> 다음 전체 스냅샷을 임시 JSON 파일로 생성
  -> 검증 성공 시 atomic rename/replace
  -> NOTICE_JSON_PATH 교체
  -> FastAPI 백엔드는 다음 요청에서 mtime 변경 감지
  -> 메모리 캐시 재로드
  -> 최신 공지 API 응답
```

핵심은 **크롤링 실행 책임과 API 요청 처리 책임을 분리**하는 것이다.

## 증분 수집과 JSON 스냅샷
증분 수집을 사용해도 MVP JSON 저장소에서는 최종 게시 파일을 **전체 스냅샷**으로 유지한다.

여기서 증분 수집은 “매번 모든 게시판의 모든 과거 공지를 다시 요청하지 않는다”는 뜻이다. API가 읽는 JSON 파일까지 신규 공지만 담은 delta 파일로 바꾼다는 뜻은 아니다.

MVP 기준 권장 흐름:

```text
1. 기존 NOTICE_JSON_PATH 전체 스냅샷 로드
2. 크롤러가 신규/최근/변경 가능성이 있는 공지만 증분 수집
3. 기존 데이터와 증분 수집 결과를 병합
4. URL/id/title 기준 중복 제거 및 최신 필드 반영
5. 병합된 전체 결과를 tmp JSON에 저장
6. tmp JSON 검증
7. 검증 성공 시 tmp JSON을 NOTICE_JSON_PATH로 atomic 교체
```

주의:

- tmp JSON이 신규 공지만 담고 있으면 atomic 교체 후 기존 공지가 API에서 사라진다.
- 따라서 JSON 저장소를 쓰는 동안 `NOTICE_JSON_PATH`는 항상 “현재 전체 공지 목록”이어야 한다.
- delta 파일을 따로 남기고 싶다면 `crawler_runs` 또는 `deltas` 용도로 별도 저장하고, API가 읽는 파일과 분리한다.
- PostgreSQL 전환 이후에는 전체 스냅샷 파일 대신 신규/수정 공지를 DB에 upsert하는 방식으로 바꿀 수 있다.

## 왜 API 서버 내부 스케줄러를 MVP에서 피하는가
FastAPI 내부에 APScheduler 같은 스케줄러를 넣을 수도 있지만, MVP에서는 권장하지 않는다.

이유:

- 운영에서 Uvicorn/Gunicorn worker가 여러 개면 크롤링이 중복 실행될 수 있다.
- 크롤링이 오래 걸리거나 실패하면 API 서버 프로세스 안정성에 영향을 줄 수 있다.
- 크롤러와 API 서버의 로그/장애 원인이 섞인다.
- 배포 환경이 바뀔 때 스케줄러 중복 실행 방지 장치가 필요해진다.

따라서 초기에는 API 서버 밖에서 크롤러를 주기 실행하는 방식이 더 단순하고 안전하다.

## 파일 갱신 방식
크롤러는 결과 파일을 직접 덮어쓰지 않는다.

구현된 게시 스크립트는 [../scripts/run_incremental_crawl_publish.sh](../scripts/run_incremental_crawl_publish.sh)다.

스크립트는 아래 방식으로 동작한다.

```text
1. 기존 NOTICE_JSON_PATH를 읽어 현재 스냅샷 확보
2. 같은 디렉터리에 임시 작업 파일 생성
3. CRAWLER_COMMAND를 실행하고 CRAWLER_OUTPUT_PATH를 임시 작업 파일로 전달
4. 크롤러는 임시 작업 파일에 병합된 전체 결과 JSON을 저장
5. JSON 파싱, 최상위 배열, 최소 레코드 수, 레코드 급감 여부 검증
6. 검증 성공 시 mv로 최종 파일 교체
7. 검증 실패 시 기존 NOTICE_JSON_PATH 유지
```

예시:

```text
NOTICE_JSON_PATH=/data/kau_official_posts.json
임시 파일=/data/.kau_official_posts.json.tmp.XXXXXX
```

이 방식은 백엔드가 파일을 읽는 도중 크롤러가 같은 파일을 쓰면서 깨진 JSON을 읽는 문제를 줄인다.

## 백엔드 JSON 재로드 정책
`JsonNoticeRepository`는 파일의 `st_mtime_ns` 수정 시각을 기준으로 캐시를 관리한다.

동작:

```text
첫 요청
  -> NOTICE_JSON_PATH 읽기
  -> 정규화
  -> 메모리 캐시 저장

이후 요청
  -> 파일 mtime 확인
  -> mtime 동일하면 캐시 사용
  -> mtime 변경되면 파일 재읽기
  -> 정규화 성공 시 캐시 교체
```

권장 fallback:

- 새 JSON 파싱에 실패하면 이전 정상 캐시를 유지한다.
- 이전 정상 캐시가 없으면 500 응답을 반환한다.
- 실패 원인은 서버 로그에 남긴다.

## 주기 설정
공지 사이트 특성상 초단위 크롤링은 필요하지 않다.

권장 기본값:

```text
개발 환경: 수동 실행
MVP 운영 환경: 30분 또는 1시간 간격
입시/수강신청 등 민감 기간: 10분~15분 간격 검토
```

크롤링 주기는 환경변수로 관리한다.

```env
CRAWLER_INTERVAL_MINUTES=60
NOTICE_JSON_PATH=/data/kau_official_posts.json
```

단, MVP에서는 백엔드가 이 값을 직접 사용할 필요는 없다. 외부 스케줄러가 이 값을 참조하거나 배포 설정에서 주기를 관리해도 된다.

## 실행 방식 선택지
### 1. 로컬 개발
개발 중에는 수동 실행이 가장 단순하다.

```bash
cd BackEnd
NOTICE_JSON_PATH=./data/kau_official_posts.json \
bash scripts/run_incremental_crawl_publish.sh
```

백엔드:

```bash
cd BackEnd
NOTICE_JSON_PATH=./data/kau_official_posts.json uvicorn app.main:app --reload --port 8000
```

### 2. 서버 cron
단일 서버 배포에서는 cron이 가장 단순하다.

예시:

```cron
*/60 * * * * cd /opt/kau-notice-backend && NOTICE_JSON_PATH=/data/kau_official_posts.json bash scripts/run_incremental_crawl_publish.sh
```

필수 환경변수:

| 이름 | 기본값 | 설명 |
| --- | --- | --- |
| `NOTICE_JSON_PATH` | `./data/kau_official_posts.json` | API가 읽는 최종 전체 스냅샷 |
| `CRAWLER_COMMAND` | `python3 -m app.crawler.main --output "$CRAWLER_OUTPUT_PATH"` | `$CRAWLER_OUTPUT_PATH`에 전체 JSON을 쓰는 크롤러 명령 |
| `MIN_RECORDS` | `1` | 게시 허용 최소 레코드 수 |
| `MIN_RETAIN_RATIO` | `0.5` | 기존 개수 대비 급감 방어 비율 |

현재 크롤러가 `--output` 파일을 기존 결과로 읽고 병합하는 방식이라면, 최종 파일을 직접 쓰지 말고 “작업 파일 복사본”을 output으로 넘긴 뒤 검증 후 최종 파일로 교체한다.

### 3. Docker Compose
API 컨테이너와 crawler 컨테이너가 같은 volume을 공유한다.

```text
api container
  - reads /data/kau_official_posts.json

crawler container
  - periodically writes /data/kau_official_posts.json atomically
```

MVP 운영에서 가장 현실적인 구조다.

### 4. 향후 DB 전환 이후
PostgreSQL 도입 후에는 크롤러가 JSON 파일만 만들지 않고, ingestion job이 DB에 upsert한다.

```text
app/crawler
  -> raw JSON 생성
  -> Ingestion job
  -> PostgreSQL upsert
  -> classification cache 갱신
  -> API는 DB 조회
```

이 단계에서 Celery, RQ, APScheduler, managed scheduler 등을 검토한다.

## 실패 처리
크롤링 실패 시 기존 공지 데이터는 유지한다.

실패 유형별 처리:

| 실패 유형 | 처리 |
| --- | --- |
| 크롤러 실행 실패 | 기존 JSON 유지, 실패 로그 기록 |
| 일부 사이트 수집 실패 | 수집 성공분만 반영할지 기존 유지할지 정책 선택 |
| 결과 JSON 파싱 실패 | 최종 파일 교체 금지 |
| 결과 레코드 수 급감 | 최종 파일 교체 보류 권장 |
| 백엔드 재로드 실패 | 이전 정상 캐시 유지 |

MVP에서는 “전체 결과 JSON이 정상일 때만 교체”를 기본 정책으로 둔다.

## 데이터 신선도 표시
프론트나 운영 모니터링에서 최신 갱신 시각을 확인할 수 있도록 `/health` 응답을 확장할 수 있다.

예상 응답:

```json
{
  "status": "ok",
  "storage": "json",
  "noticeCount": 1250,
  "lastLoadedAt": "2026-04-27T10:20:30+09:00",
  "sourceUpdatedAt": "2026-04-27T10:18:02+09:00"
}
```

MVP 초기에는 `status`만 반환하고, 운영 필요성이 생기면 추가한다.

## MVP 결정
초기 백엔드에서는 아래 구조를 기준으로 한다.

```text
FastAPI API 서버
  - 공지 JSON 읽기
  - mtime 기반 캐시
  - 요청 시 최신 파일 감지

외부 크롤링 작업
  - cron 또는 별도 컨테이너에서 주기 실행
  - 기존 스냅샷과 증분 수집 결과를 병합
  - 병합된 전체 스냅샷을 임시 파일에 저장
  - 검증 후 atomic 교체
```

이 구조는 단순하면서도 나중에 PostgreSQL ingestion job으로 자연스럽게 확장할 수 있다.
