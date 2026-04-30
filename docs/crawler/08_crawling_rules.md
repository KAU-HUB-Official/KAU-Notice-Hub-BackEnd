# 크롤링 규칙 상세

이 문서는 현재 크롤러의 수집 정책을 운영 관점에서 설명합니다.
기준 코드:

- `app/crawler/main.py`
- `app/crawler/services/board_crawler.py`
- `app/crawler/services/board_registry.py`
- `app/crawler/policies/notice_policy.py`
- `app/crawler/services/url_normalizer.py`
- `app/crawler/services/dedup_service.py`

## 1) 페이지 순회

- 기본값 `--max-pages 0`은 페이지 상한 없이 순회합니다.
- `--max-pages N`처럼 양수를 지정하면 보드별 최대 N페이지까지만 순회합니다.
- adapter에 `min_pages_field`가 있으면 `page_limit = max(max_pages, min_pages)`를 사용합니다.
  - 예: `job_notice`는 `min_pages=2`
- 목록 항목은 `url`, `page`, `is_permanent_notice`로 관리합니다.
- 다음 조건 중 하나를 만나면 해당 보드의 페이지 순회를 종료합니다.
- 일반공지에서 최근성 기준 미충족/게시일 미확인 항목 발견
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
  - `published_at` 파싱 성공 + `published_date > cutoff_date`인 경우만 포함
  - 그 외(컷오프 이전/같은 날짜, 게시일 미확인)는 제외 + 해당 보드 수집 즉시 중단

## 4) 증분 수집

- 실행 시작 시 결과 파일(`--output`)의 `original_url`과 `source_meta[].original_url`을 읽어 `known_urls` 캐시를 구성합니다.
- 캐시에 있는 URL은 상세 요청하지 않습니다.
- 캐시에 있는 일반공지도 기존 `published_at`을 평가해 1년 초과/게시일 미확인이면 해당 보드 수집을 중단합니다.
- 새로 수집된 post의 canonical URL은 즉시 `known_urls`에 반영됩니다.

## 5) 오래된 공지 삭제

증분 수집은 최종 JSON을 전체 스냅샷으로 유지하므로, 기존 파일에 남아 있던 오래된 공지는 병합 이후 별도로 제거합니다.

- 삭제 시점: 기존 데이터와 신규 수집 결과를 병합하고 중복 제거한 뒤, 최종 JSON 저장 직전
- 삭제 대상: 게시일을 파싱할 수 있고 `published_date <= today - 365일`인 일반공지
- 보존 대상:
  - 상시공지(`is_permanent_notice=true`)
  - 게시일을 파싱할 수 없어 1년 초과 여부를 확정할 수 없는 공지
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

## 7) 실패 기록

- `request_failed`
- `parse_error:<Exception>`
- `required_field_empty` (`title` 누락 또는 첨부파일 fallback도 불가능한 `content` 누락)
- `robots_disallowed`
- `missing_ntt_id` (`kau_college`)

## 8) 운영 시 참고

- `max_posts` 설정값은 현재 상세 수집 상한으로 직접 사용되지 않습니다.
- 정책 변경 시 다음 파일을 함께 업데이트해야 합니다.
  - `app/crawler/policies/notice_policy.py`
  - `app/crawler/services/board_crawler.py`
  - `app/crawler/services/dedup_service.py`
  - 본 문서(`docs/08_crawling_rules.md`)

## 9) 카드형 학과/대학 게시판

- `kau_card_notice`는 `notice.php?code=...&page=...` 구조를 쓰는 학과/대학 홈페이지에 사용합니다.
- 현재 대상은 `aisw.kau.ac.kr`, `ai.kau.ac.kr:8100/8110/8120/8130/8140`, `sw.kau.ac.kr`, `ave.kau.ac.kr`입니다.
- 상세 URL은 `code`, `mode`, `seq`만 남기도록 canonical 정규화합니다.
