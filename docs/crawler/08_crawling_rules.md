# 크롤링 규칙 상세

이 문서는 현재 크롤러의 수집 정책을 운영 관점에서 설명합니다.
기준 코드:

- `app/crawler/main.py`
- `app/crawler/services/board_crawler.py`
- `app/crawler/services/board_registry.py`
- `app/crawler/policies/notice_policy.py`
- `app/crawler/services/url_normalizer.py`
- `app/crawler/services/dedup_service.py`
- `app/crawler/services/content_enrichment_service.py`
- `app/crawler/services/content_asset_downloader.py`
- `app/crawler/services/content_extractors/`

## 1) 페이지 순회

- 기본값 `--max-pages 0`은 페이지 상한 없이 순회합니다.
- `--max-pages N`처럼 양수를 지정하면 보드별 최대 N페이지까지만 순회합니다.
- adapter에 `min_pages_field`가 있으면 `page_limit = max(max_pages, min_pages)`를 사용합니다.
  - 예: `job_notice`는 `min_pages=2`
- 목록 항목은 `url`, `page`, `is_permanent_notice`로 관리합니다.
- 다음 조건 중 하나를 만나면 해당 보드의 페이지 순회를 종료합니다.
  - 일반공지 항목이 있는 페이지에서 일반공지 신규 URL 0건 발견
  - 일반공지에서 1년 초과 항목 발견
  - 목록 항목 0건
  - 이전에 본 페이지와 동일한 URL 목록 반복
  - 목록 요청 실패

## 2) 상세 수집 순서

- 페이지별 상세 대상은 다음 순서로 재정렬됩니다.
  1. 상시공지(`is_permanent_notice=true`)
  2. 일반공지(`is_permanent_notice=false`)
- 상시공지를 먼저 처리해 오래된 공지라도 누락되지 않도록 합니다.
- 상시공지를 제외한 일반공지는 목록에서 최신순으로 정렬된다는 전제로 중단 정책을 적용합니다.

## 3) 최근성 정책 (`RECENT_NOTICE_DAYS = 365`)

컷오프 계산:

- `cutoff_date = today - 365일`
- 최근 공지 판단식: `published_date > cutoff_date`

즉, 컷오프 날짜와 같은 날짜는 최근으로 보지 않습니다.

세부 동작:

- 상시공지
  - 게시일과 무관하게 포함
- 일반공지
  - `published_date > cutoff_date`인 경우 포함
  - `published_date <= cutoff_date`인 경우 제외 + 해당 보드 수집 즉시 중단

## 4) 증분 수집

- 실행 시작 시 결과 파일(`--output`)의 `original_url`과 `source_meta[].original_url`을 읽어 `known_urls` 캐시를 구성합니다.
- 캐시에 있는 URL은 상세 요청하지 않습니다.
- 일반공지는 최신순으로 정렬된다는 전제로, 현재 페이지에 일반공지 항목이 있고 일반공지 신규 URL이 0건이면 해당 보드 수집을 중단합니다.
- 상시공지만 있는 페이지는 이 조건으로 중단하지 않고 다음 페이지를 계속 확인합니다.
- 이때 같은 페이지에 신규 상시공지가 있으면 먼저 상세 수집한 뒤 중단합니다.
- 신규 일반공지와 기존 일반공지가 섞인 페이지에서는 기존 `published_at`도 평가해 1년 초과면 해당 보드 수집을 중단합니다.
- 새로 수집된 post의 canonical URL은 즉시 `known_urls`에 반영됩니다.

목록 로그는 아래 형태로 남깁니다.

```text
목록 | 게시판=일반공지 | 페이지=1 | 전체=10 | 신규=2 | 상시공지=1 | 일반공지=9 | 신규일반공지=2
```

수집 종료 사유는 `수집 종료 | 게시판=... | 사유=...` 형태로 남깁니다. 주요 사유는 `신규 일반공지 없음`, `일반공지 1년 초과`, `목록 없음`, `반복 목록`, `목록 요청 실패`, `robots 차단`입니다.

## 5) 오래된 공지 삭제

증분 수집은 최종 JSON을 전체 스냅샷으로 유지하므로, 기존 파일에 남아 있던 오래된 공지는 병합 이후 별도로 제거합니다.

- 삭제 시점: 기존 데이터와 신규 수집 결과를 병합하고 중복 제거한 뒤, 최종 JSON 저장 직전
- 삭제 대상: 게시일을 파싱할 수 있고 `published_date <= today - 365일`인 일반공지
- 보존 대상:
  - 상시공지(`is_permanent_notice=true`)
  - 제목 중복 병합 공지 중 하나라도 최근 게시일 또는 상시공지 메타가 있는 공지
- 삭제 건수는 최종 저장 로그의 `stale_pruned` 값으로 확인합니다.
- 발행 전 레코드 급감 검증은 기존 전체 건수가 아니라 기존 보존 대상 건수를 기준으로 수행합니다.

## 6) 중복 제거

- 1차: URL canonicalization 기준 중복 제거
- 2차: 제목 정규화 기준 통합
  - 공백 정리
  - 소문자화

제목 통합 시:

- 동일 제목 공지를 1건으로 저장
- `source_name`, `source_type`, `category_raw`를 배열로 병합
- `source_meta` 배열에 출처 메타 누적
- 첨부파일은 URL 기준으로 병합

## 7) content 보강

`CONTENT_ENRICHMENT_ENABLED=true`이면 병합/중복 제거/오래된 공지 삭제 이후, 최종 JSON 저장 직전에 content 보강을 시도합니다.

보강 후보:

- 보강 가능한 이미지/HWP/HWPX asset이 있고, `content`가 `[이미지 본문]`, `[동영상 본문]`, `[첨부파일 공지]`, `본문 정보가 비어 있습니다.` 같은 fallback 문자열인 경우
- 본문 텍스트가 `CONTENT_ENRICHMENT_MIN_TEXT_LENGTH` 미만이고 본문 이미지 또는 이미지/HWP/HWPX 첨부가 있는 경우

처리 기준:

- 본문 이미지 URL은 상세 HTML에서 `content_assets`로 기록합니다.
- 본문 동영상 iframe은 크롤링 실패로 보내지 않고 fallback content로 최소 정보를 보존합니다. 현재 LLM 보강 대상은 이미지/HWP/HWPX입니다.
- 첨부파일은 파일명/URL/Content-Type 기준으로 이미지 또는 HWP/HWPX만 처리합니다.
- asset 다운로드는 HTTP(S), 공개 IP, allowlist 도메인, 파일 크기 상한을 통과해야 합니다.
- 공지 1건에 여러 asset이 있으면 실패한 asset은 `asset_errors`에 남기고 남은 asset 처리를 계속합니다.
- OpenAI provider는 이미지 텍스트 추출과 최종 content 생성을 담당합니다.
- HWPX는 ZIP/XML 직접 파싱을 먼저 시도하고, HWP/HWPX는 `unhwp` 기반 로컬 extractor로 fallback합니다.
- `unhwp`를 import할 수 없는 환경에서는 `extract-hwp` 패키지가 import 가능한 경우 선택적 fallback으로 사용합니다.
- 성공 시 `content_original`에 기존 fallback을 보존하고 `content`를 생성 결과로 교체합니다.
- 실패 시 기존 `content`를 유지하고 `content_enrichment.status=failed`와 `error_code`를 기록합니다.
- 호출 예산이 소진되면 남은 후보는 `content_enrichment.status=skipped`, `reason=enrichment_call_budget_exceeded`로 기록하고 다음 실행에서 다시 시도할 수 있게 둡니다.

완료 로그의 `보강대상`은 이번 실행에서 보강 후보로 잡힌 공지 수입니다. `시도`는 보강 후보 중 실제 성공/실패 판정까지 진행한 수입니다. `호출`이 `CONTENT_ENRICHMENT_MAX_CALLS_PER_RUN`에 도달하면 이후 후보는 실패가 아니라 skip으로 남고, `보강대상`에는 포함되지만 `시도`에는 포함되지 않습니다.

`content_enrichment.trigger` 분류:

| trigger | 의미 |
| --- | --- |
| `inline_image_and_mixed_attachments` | 본문 이미지, 이미지 첨부, HWP/HWPX 첨부가 모두 있음 |
| `inline_image_and_hwp_attachment` | 본문 이미지와 HWP/HWPX 첨부가 같이 있음 |
| `inline_image_and_image_attachment` | 본문 이미지와 이미지 첨부가 같이 있음 |
| `mixed_attachments` | 이미지 첨부와 HWP/HWPX 첨부가 같이 있음 |
| `image_only_body` | 본문 이미지 중심 공지 |
| `hwp_attachment_only` | HWP/HWPX 첨부 중심 공지 |
| `image_attachment_only` | 이미지 첨부 중심 공지 |
| `inline_image` | 텍스트가 짧고 본문 이미지가 있음 |
| `unknown` | 위 조건에 들어가지 않는 보강 시도 |

## 8) 실패 기록

- `request_failed`
- `parse_error:<Exception>`
- `required_field_empty:<fields>` (`title` 누락 또는 본문 이미지/동영상/첨부파일 fallback도 불가능한 `content` 누락. `missing_fields` 배열도 함께 기록)
- `robots_disallowed`
- `missing_ntt_id` (`kau_college`)

content 보강 실패는 위 실패 기록 파일에 쓰지 않고 각 post의 `content_enrichment` metadata에 기록합니다.

## 9) 운영 시 참고

- `max_posts` 설정값은 현재 상세 수집 상한으로 직접 사용되지 않습니다.
- 정책 변경 시 다음 파일을 함께 업데이트해야 합니다.
  - `app/crawler/policies/notice_policy.py`
  - `app/crawler/services/board_crawler.py`
  - `app/crawler/services/dedup_service.py`
  - `app/crawler/services/content_enrichment_service.py`
  - `app/crawler/services/content_asset_downloader.py`
  - `app/crawler/services/content_extractors/`
  - 본 문서(`docs/crawler/08_crawling_rules.md`)

## 10) 카드형 학과/대학 게시판

- `kau_card_notice`는 `notice.php?code=...&page=...` 구조를 쓰는 학과/대학 홈페이지에 사용합니다.
- 현재 대상은 `aisw.kau.ac.kr`, `ai.kau.ac.kr:8100/8110/8120/8130/8140`, `sw.kau.ac.kr`, `ave.kau.ac.kr`입니다.
- 상세 URL은 `code`, `mode`, `seq`만 남기도록 canonical 정규화합니다.
