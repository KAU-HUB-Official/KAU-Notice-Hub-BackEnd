# 주기 크롤링 및 공지 데이터 갱신

## 범위
이 문서는 백엔드 서버가 실행 중인 동안 크롤러를 주기적으로 실행하고, 최신 공지 데이터를 API에 반영하는 방식을 정의한다.

현재 MVP에서는 구조를 복잡하게 만들지 않는다.

- FastAPI 서버는 공지 조회 API를 안정적으로 제공한다.
- 크롤러 코드는 `app/crawler`에 포함하고, FastAPI lifespan에서 시작한 백그라운드 task가 주기 실행한다.
- 크롤러 결과는 JSON 파일(`NOTICE_JSON_PATH`)로 atomic하게 게시된다. JSON은 안전망/아카이브 역할이다.
- JSON 게시 직후 `app/ingest.py`가 동일 데이터를 SQLite DB(`NOTICE_DB_PATH`)에 atomic하게 반영한다.
- 백엔드는 SQLite DB를 읽어 응답한다. DB가 없으면 기동 시 JSON에서 자동 부트스트랩한다.
- Redis, Celery, 별도 queue, 복잡한 worker는 MVP에서 사용하지 않는다.

## 현재 MVP 구조
```text
FastAPI app startup
  -> crawler scheduler task 시작
  -> app/crawler 실행
  -> 기존 스냅샷 기준 증분 수집
  -> 기존 데이터와 신규/수정 데이터 병합
  -> 1년 초과 일반공지 삭제
  -> 선택적으로 이미지/HWP 기반 content 보강
  -> 다음 전체 스냅샷을 임시 JSON 파일로 생성
  -> 검증 성공 시 atomic rename/replace로 NOTICE_JSON_PATH 교체
  -> app/ingest.py가 동일 데이터를 임시 .db에 작성
  -> ingest 시 모든 (audience, source_group) 조합의 facet을 미리 계산해 notice_facets_cache에 저장
  -> atomic rename으로 NOTICE_DB_PATH 교체
  -> 다음 API 요청은 새 SQLite 커넥션에서 최신 데이터 조회
```

핵심은 **크롤링 실행을 API 요청 처리 경로 밖의 백그라운드 task로 분리**하는 것이다.

### ingest 시 facet 미리 계산

목록/검색 응답의 facet(필터 선택지)은 데이터가 바뀔 때만(즉 ingest 시) 달라진다. 따라서 요청마다 재계산하지 않고 ingest 시 `app/ingest.py`가 `build_and_store_facets`로 한 번 계산해 `notice_facets_cache` 테이블에 저장한다. API 읽기 경로는 이 캐시를 조회하고, 캐시 미스(이전 스키마 DB, 데이터에 없는 audience)면 기존처럼 live로 계산해 동작을 보존한다. 본문 Markdown도 같은 원리로 ingest 시 `content_markdown` 컬럼에 미리 정규화해 둔다. 자세한 스키마는 `docs/ERD.md`를 참고한다.

### 스키마 버전 변경 시 재ingest

`app/db.py`의 `SCHEMA_VERSION`이 바뀌면, 다음 앱 기동 시 `app/dependencies.py`가 버전 불일치를 감지해 기존 `NOTICE_DB_PATH`를 제거하고 JSON에서 자동으로 다시 ingest한다. 수동 조치는 필요 없지만, 배포 직후 첫 크롤러 게시/ingest가 완료되기 전까지는 부트스트랩 ingest가 첫 요청 경로에서 한 번 실행될 수 있다.

## 증분 수집과 JSON 스냅샷
증분 수집을 사용해도 MVP JSON 저장소에서는 최종 게시 파일을 **전체 스냅샷**으로 유지한다.

여기서 증분 수집은 “매번 모든 게시판의 모든 과거 공지를 다시 요청하지 않는다”는 뜻이다. API가 읽는 JSON 파일까지 신규 공지만 담은 delta 파일로 바꾼다는 뜻은 아니다.

MVP 기준 권장 흐름:

```text
1. 기존 NOTICE_JSON_PATH 전체 스냅샷 로드
2. 크롤러가 신규/최근/변경 가능성이 있는 공지만 증분 수집
3. 기존 데이터와 증분 수집 결과를 병합
4. URL/id/title 기준 중복 제거 및 최신 필드 반영
5. 게시일 기준 1년 이상 지난 일반공지를 병합 결과에서 제거
6. `CONTENT_ENRICHMENT_ENABLED=true`이면 본문이 비어 있는 이미지/HWP 공지의 `content` 보강
7. 병합된 전체 결과를 tmp JSON에 저장
8. tmp JSON 검증
9. 검증 성공 시 tmp JSON을 NOTICE_JSON_PATH로 atomic 교체
```

주의:

- tmp JSON이 신규 공지만 담고 있으면 atomic 교체 후 기존 공지가 API에서 사라진다.
- 따라서 JSON 저장소를 쓰는 동안 `NOTICE_JSON_PATH`는 항상 “현재 전체 공지 목록”이어야 한다.
- 증분 수집 후 오래된 일반공지는 최종 전체 스냅샷에서 제거한다. 상시공지는 게시일과 무관하게 보존하고, 게시일을 파싱할 수 없는 항목은 1년 초과 여부를 확정할 수 없으므로 삭제하지 않는다.
- 레코드 급감 검증은 오래된 일반공지를 제외한 기존 보존 대상 건수를 기준으로 수행한다. 의도된 stale 삭제가 `MIN_RETAIN_RATIO`/`CRAWLER_MIN_RETAIN_RATIO`에 막히지 않도록 하기 위함이다.
- content 보강은 실패해도 크롤링 실패로 취급하지 않는다. 실패한 공지는 기존 fallback `content`를 유지하고 `content_enrichment.status=failed`만 기록한다.
- delta 파일을 따로 남기고 싶다면 `crawler_runs` 또는 `deltas` 용도로 별도 저장하고, API가 읽는 파일과 분리한다.

## API 서버 내부 스케줄러 운영 기준
현재 구현은 APScheduler 같은 외부 scheduler 라이브러리 없이 FastAPI lifespan에서 `asyncio` background task를 시작한다.

주의점:

- 운영에서 Uvicorn/Gunicorn worker가 여러 개면 크롤링이 중복 실행될 수 있다.
- 크롤링은 오래 걸릴 수 있으므로 요청 처리 함수 안에서 실행하면 안 된다.
- 크롤러와 API 서버의 로그/장애 원인이 섞인다.
- 배포 환경이 바뀔 때 스케줄러 중복 실행 방지 장치가 필요하다.

이를 위해 현재 구현은 아래 방식을 사용한다.

- `CRAWLER_SCHEDULER_ENABLED=true`일 때만 서버 내장 스케줄러를 켠다.
- Docker Compose의 `api` 서비스는 기본값으로 스케줄러를 켠다.
- 크롤링은 `asyncio.to_thread()`로 실행해 event loop를 막지 않는다.
- 같은 JSON 디렉터리의 `.crawler.lock` 파일로 중복 실행을 방지한다.
- 결과는 임시 파일에 쓴 뒤 검증 성공 시 `os.replace()`로 atomic 교체한다.
- `NOTICE_AUTO_LABEL_ENABLED=true`면 JSON 교체 뒤, ingest 전에 라벨 없는 공지에 적용 대상 라벨을 붙인다([공지 대상 자동 라벨](#공지-대상-자동-라벨)).

## 공지 대상 자동 라벨

연구 세션의 확정 라벨(`NOTICE_LABELS_PATH`)은 정해진 시점까지의 공지만 덮는다. 그 뒤에 수집된 공지는 `app/notice_auto_label.py`가 라벨을 붙여 `NOTICE_AUTO_LABELS_PATH`(기본 `/data/notice_labels_auto.jsonl`)에 쌓는다. ingest는 연구 라벨을 먼저 쓰고, 연구 라벨이 없는 공지에만 자동 라벨을 쓴다.

1. 연구 라벨과 자동 라벨이 모두 없는 공지만 본다. 한 번 붙인 자동 라벨은 다시 만들지 않는다.
2. 게시판 규칙을 먼저 적용한다. 연구 코드 `noticebench/board_rules.py`의 `decide()`와 같은 규칙이다(입찰 → 외부, 산학협력단 → 교직원, 부속기관 → 부속기관교육생, 특수대학원 → 그 대학원, 학과 → 학부재학생 등). 연구 코퍼스 7,857건에서 연구 코드와 판정이 모두 같다.
3. 학교 전체 게시판이거나, 제목·본문에 다른 대상을 가리키는 말이 있는 공지는 LLM(`NOTICE_AUTO_LABEL_MODEL`, 기본 `gpt-6-luna`, `reasoning.effort` `none`, 구조화 출력)이 연구 라벨 기준서 v5의 대상 규칙으로 정한다. 본문은 3,000자까지 넘긴다.
   - LLM 결과에서 학부재학생과 대학원 셋이 모두 있으면 빈 목록(모두)으로 바꾼다.
   - 신입생 제외(excludes)는 수강신청·수강지도상담·등록 공지에만 남긴다.
4. 한 번 수집할 때 LLM에 보내는 공지는 `NOTICE_AUTO_LABEL_MAX_LLM_CALLS_PER_RUN`(기본 100)건까지다. 남은 공지와 호출이 실패한 공지는 기록하지 않고 다음 수집 때 다시 본다. `OPENAI_API_KEY`가 없으면 규칙 라벨만 붙인다.
5. 라벨링이 실패해도 JSON 게시와 ingest는 그대로 진행한다.

자동 라벨 줄은 연구 라벨 파일과 같은 형식이고, `label_source`가 `auto_rule` 또는 `auto_llm`, `label_version`이 `auto-v5-2026-10-15`다. LLM 라벨에는 `model`과 판단 근거(`reason`)도 남는다.

LLM 라벨 품질(2026-10-15): 연구 재수집본 7,857건 중 사람 검수 라벨이 있고 규칙이 LLM에 넘기는 공지 326건으로 쟀다. 지표는 학생 넷과 교직원·기타 다섯 단위의 보임 여부가 사람 라벨과 모두 같은 비율, 사람 라벨로는 보여야 하는데 숨긴 (공지, 단위) 수(숨김), 보이지 않아야 하는데 보인 수(과다)다.

| 모델 | 일치 | 숨김 | 과다 | 326건 비용 |
| --- | --- | --- | --- | --- |
| **gpt-6-luna** (effort `none`, 기본) | **76.7%** | **101** | 72 | 약 $0.04 (입력 70%가 캐시) |
| gpt-4.1-mini (temperature 0) | 73.9% | 140 | 58 | 약 $0.36 (같은 토큰 기준 추정) |
| 연구 라벨 초안(Claude Sonnet, 운영 라벨 대부분의 출처) | 70.9% | 130 | 33 | — |

- 프롬프트는 gpt-4.1-mini로 100건을 보며 고쳤고, 결과 정리 두 가지(학부재학생과 대학원 셋 → 빈 목록, excludes는 수강신청·수강지도상담·등록 공지만)는 나머지 226건의 gpt-4.1-mini 오류를 보고 정했다. gpt-6-luna에는 이 과정이 없었다. 226건만 보면 gpt-6-luna 77.4%, gpt-4.1-mini 73.9%다.
- 초안 수치는 검수자가 초안을 보며 검수했으므로 초안 쪽에 유리하다.
- 남은 실수는 대학원 쪽을 좁게 붙이는 것이 가장 많다(특수대학원생 숨김 34, 일반대학원생 숨김 30).

새 게시판을 크롤러에 추가하면 `app/notice_auto_label.py`의 게시판 집합(`SCHOOL`, `SPECIAL`, `INSTITUTE` 등) 중 어디에 속하는지 정한다. 어디에도 없으면 학과 게시판으로 보고 학부재학생 규칙을 쓴다.

## 파일 갱신 방식
크롤러는 결과 파일을 직접 덮어쓰지 않는다.

서버 내장 구현은 [../app/crawler_scheduler.py](../app/crawler_scheduler.py)다. 수동 1회 실행용 스크립트는 [../scripts/run_incremental_crawl_publish.sh](../scripts/run_incremental_crawl_publish.sh)다.

서버 내장 스케줄러는 JSON publish 후 같은 데이터로 SQLite ingest까지 수행한다.

수동 스크립트는 아래 방식으로 JSON publish를 수행한다.

```text
1. 기존 NOTICE_JSON_PATH를 읽어 현재 스냅샷 확보
2. 같은 디렉터리에 임시 작업 파일 생성
3. `app.crawler.main.crawl_all_notices()`를 임시 작업 파일 경로로 실행
4. 크롤러는 임시 작업 파일에 병합된 전체 결과 JSON을 저장
5. JSON 파싱, 최상위 배열, 최소 레코드 수, 레코드 급감 여부 검증
   - 급감 여부는 기존 스냅샷에서 1년 이상 지난 일반공지를 제외한 건수를 기준으로 비교
6. 검증 성공 시 mv로 최종 파일 교체
7. 검증 실패 시 기존 NOTICE_JSON_PATH 유지
```

수동 스크립트만 실행한 경우 DB는 즉시 교체되지 않는다. API 프로세스는 다음 기동 시 DB가 없거나 스키마가 맞지 않으면 JSON에서 다시 부트스트랩하고, 서버 내장 스케줄러 publish 경로에서는 JSON 교체 직후 `app/ingest.py`가 `NOTICE_DB_PATH`를 atomic 교체한다.

예시:

```text
NOTICE_JSON_PATH=/data/kau_official_posts.json
임시 파일=/data/.kau_official_posts.json.tmp.XXXXXX
```

이 방식은 백엔드가 파일을 읽는 도중 크롤러가 같은 파일을 쓰면서 깨진 JSON을 읽는 문제를 줄인다.

### 남은 임시 파일 정리

임시 파일은 정상 종료나 예외 시 `finally`(스크립트는 `trap EXIT`)에서 지운다. 하지만 프로세스가 강제 종료되면(`mem_limit` OOM kill, 배포 시 컨테이너 재생성 등) 정리 코드가 실행되지 않아 전체 스냅샷 크기(수십~100MB)의 임시 파일이 `/data`에 남는다. 서버 내장 스케줄러는 `.kau_official_posts.json.tmp.XXXXXXXX`(8자), 수동 스크립트는 `.kau_official_posts.json.tmp.XXXXXX`(6자) 형태로 만든다.

서버 내장 스케줄러는 publish마다 `.crawler.lock`을 잡은 직후, 새 임시 파일을 만들기 전에 수정 시각이 6시간(`STALE_TEMP_SNAPSHOT_MAX_AGE_SECONDS`) 이상 지난 `.{NOTICE_JSON_PATH 파일명}.tmp.*`를 지운다. `CRAWLER_RUN_ON_STARTUP=true`이면 api 기동 직후 첫 publish에서 정리된다.

- lock을 못 잡으면(다른 publish 진행 중) 정리하지 않는다.
- 크롤러는 결과를 마지막에 한 번만 쓰므로 진행 중인 임시 파일의 mtime은 생성 시각이다. 6시간은 크롤링 소요 시간보다 충분히 길게 잡은 값이다.
- 수동 스크립트는 `.crawler.lock`을 잡지 않으므로, 수동 크롤링이 6시간 넘게 이어지면 그 임시 파일이 지워질 수 있다.
- `kau_official_posts.json`, `*.bak*`, DB 임시 파일(`.kau_notice_hub.db.tmp.*`)은 대상이 아니다.
- 지운 개수와 용량은 `app.crawler_scheduler` INFO 로그(`removed stale temp snapshots: count=... bytes=...`)로 남는다.

이미 쌓인 파일을 손으로 정리하는 절차는 [DEPLOYMENT.md의 `/data` 임시 스냅샷 정리](./DEPLOYMENT.md#data-임시-스냅샷-정리)를 따른다.

## JSON fallback 재로드 정책
API의 기본 repository는 SQLite다. 다만 DB 부트스트랩이 실패하거나 JSON fallback을 사용하는 경우 `JsonNoticeRepository`가 파일의 `st_mtime_ns` 수정 시각을 기준으로 캐시를 관리한다.

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
개발 환경: 수동 실행 또는 `CRAWLER_SCHEDULER_ENABLED=true`
MVP 운영 환경: 3시간 간격
입시/수강신청 등 민감 기간: 10분~15분 간격 검토
```

크롤링 주기는 환경변수로 관리한다.

```env
NOTICE_JSON_PATH=/data/kau_official_posts.json
NOTICE_DB_PATH=/data/kau_notice_hub.db
CRAWLER_SCHEDULER_ENABLED=true
CRAWLER_INTERVAL_SECONDS=10800
CRAWLER_RUN_ON_STARTUP=true
```

`CRAWLER_INTERVAL_SECONDS=10800`은 3시간이다.

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
NOTICE_JSON_PATH=./data/kau_official_posts.json \
NOTICE_DB_PATH=./data/kau_notice_hub.db \
uvicorn app.main:app --reload --port 8000
```

서버 내장 스케줄러까지 켜서 확인하려면:

```bash
CRAWLER_SCHEDULER_ENABLED=true \
CRAWLER_INTERVAL_SECONDS=10800 \
NOTICE_JSON_PATH=./data/kau_official_posts.json \
NOTICE_DB_PATH=./data/kau_notice_hub.db \
uvicorn app.main:app --reload --port 8000
```

### 2. 서버 내장 스케줄러
배포 기본 방식이다.

| 이름 | 기본값 | 설명 |
| --- | --- | --- |
| `NOTICE_JSON_PATH` | `./data/kau_official_posts.json` | API가 읽는 최종 전체 스냅샷 |
| `NOTICE_DB_PATH` | `./data/kau_notice_hub.db` | API가 우선 읽고 ingest가 atomic 교체하는 SQLite DB |
| `CRAWLER_SCHEDULER_ENABLED` | `false` | 서버 내장 크롤러 스케줄러 활성화 |
| `CRAWLER_INTERVAL_SECONDS` | `10800` | 크롤링 주기. 3시간 |
| `CRAWLER_RUN_ON_STARTUP` | `true` | 서버 시작 직후 1회 실행 |
| `CRAWLER_MAX_PAGES` | `0` | 게시판별 목록 페이지 상한 |
| `CRAWLER_MIN_RECORDS` | `1` | 게시 허용 최소 레코드 수 |
| `CRAWLER_MIN_RETAIN_RATIO` | `0.5` | 기존 개수 대비 급감 방어 비율 |
| `CRAWLER_LOCK_PATH` | 없음 | 지정하지 않으면 JSON 디렉터리의 `.crawler.lock` 사용 |
| `CRAWLER_RECENT_NOTICE_DAYS` | `365` | 일반공지 수집·정리 기간(일). 넓은 기간을 한 번 모을 때만 바꾸고 `app.crawler.main`을 직접 실행한다. 게시 스크립트의 게시 전 정리는 365일 고정 |
| `CRAWLER_RECHECK_DAYS` | `7` | 이미 수집한 공지 중 게시일이 이 일수 이내인 것은 상세를 다시 읽어 원문 해시가 바뀌면 갱신. 상시공지는 기간과 무관하게 매 수집 확인 |
| `CRAWLER_REQUEST_DELAY_SECONDS` | `0.5,1.2` | 요청 사이 대기 시간 범위(초, `최소,최대`) |
| `CONTENT_ENRICHMENT_ENABLED` | `false` | 이미지/HWP 기반 content 보강 활성화 |
| `CONTENT_ENRICHMENT_MAX_CALLS_PER_RUN` | `50` | crawl 1회당 보강 API 호출 상한 |
| `OPENAI_API_KEY` | 없음 | OpenAI provider 사용 시 필요 |

현재 크롤러가 `--output` 파일을 기존 결과로 읽고 병합하는 방식이라면, 최종 파일을 직접 쓰지 말고 “작업 파일 복사본”을 output으로 넘긴 뒤 검증 후 최종 파일로 교체한다.

### 3. Docker Compose
API 컨테이너가 같은 volume 안의 JSON을 읽고, 내장 스케줄러가 같은 파일을 atomic 교체한다.

```text
api container
  - reads /data/kau_official_posts.json
  - reads /data/kau_notice_hub.db first when available
  - starts crawler scheduler on app startup
  - writes /data/kau_official_posts.json atomically every 3 hours
  - ingests the published JSON into /data/kau_notice_hub.db atomically
```

MVP 운영에서 가장 현실적인 구조다.

## 실패 처리
크롤링 실패 시 기존 공지 데이터는 유지한다.

실패 유형별 처리:

| 실패 유형 | 처리 |
| --- | --- |
| 크롤러 실행 실패 | 기존 JSON 유지, 실패 로그 기록 |
| 일부 사이트 수집 실패 | 수집 성공분만 반영할지 기존 유지할지 정책 선택 |
| 결과 JSON 파싱 실패 | 최종 파일 교체 금지 |
| 결과 레코드 수 급감 | 최종 파일 교체 보류 권장 |
| 자동 라벨링 실패 | 로그만 남기고 ingest 진행. 실패한 공지는 다음 수집 때 다시 라벨링 |
| 백엔드 재로드 실패 | 이전 정상 캐시 유지 |

MVP에서는 “전체 결과 JSON이 정상일 때만 교체”를 기본 정책으로 둔다.

## MVP 결정
초기 백엔드에서는 아래 구조를 기준으로 한다.

```text
FastAPI API 서버
  - SQLite DB 우선 읽기
  - DB가 없거나 스키마가 맞지 않으면 JSON에서 부트스트랩
  - JSON도 없으면 JsonNoticeRepository fallback

내장 크롤링 작업
  - FastAPI lifespan 백그라운드 task에서 3시간마다 실행
  - 중복 실행 방지를 위해 JSON 디렉터리의 .crawler.lock 사용
  - 기존 스냅샷과 증분 수집 결과를 병합
  - 병합된 전체 스냅샷을 임시 파일에 저장
  - 검증 후 JSON atomic 교체
  - 같은 JSON을 SQLite DB로 atomic ingest
```
