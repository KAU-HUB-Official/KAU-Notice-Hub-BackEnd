# 문제 해결 및 개선 이력

이 문서는 크롤러 구현 중 병목을 실제 로직으로 줄였거나, 단순 설정 변경으로 해결하기 어려운 작업을 특정 구현 로직으로 해결한 사례만 기록합니다.

운영 중 장애 대응 절차와 실패 코드 정의는 [운영/장애 대응](./06_operations_and_failure.md)을 따르고, 현재 동작 정책은 [크롤링 규칙 상세](./08_crawling_rules.md)을 기준으로 합니다.

## 기록 기준

이 문서에는 아래 조건 중 하나를 만족하는 항목만 추가합니다.

- 병목 해소: 구현된 로직이 불필요한 요청, 반복 처리, 처리 시간, 비용 같은 병목을 줄인 경우
- 고난도 task 해결: 사이트 응답, 첨부 형식, 데이터 품질처럼 단순한 옵션 변경으로 해결하기 어려운 문제를 특정 로직으로 처리한 경우

아래 항목은 이 문서의 기록 대상이 아닙니다.

- 로그 문구, 포맷, reason 이름처럼 운영 가독성만 바꾼 변경
- 문서 설명 보강 또는 기존 정책 정리
- 작은 버그 수정, 테스트 추가, 예외 메시지 구체화
- 아직 구현되지 않은 개선 계획

## 요약

| 영역 | 문제 상황 | 핵심 구현 로직 | 개선 결과 |
| --- | --- | --- | --- |
| 이미지/HWP/HWPX content 보강 | 이미지 또는 HWP 첨부에 실제 공지 내용이 들어 있어 기본 크롤링만으로 검색 가능한 본문을 만들기 어려움 | asset 수집, 안전한 다운로드, 이미지/HWP/HWPX 텍스트 추출, LLM 기반 Markdown content 생성 | fallback content를 검색 가능한 본문으로 교체하고 원본 fallback은 `content_original`에 보존 |
| 증분 수집 병목 최적화 | 로그 분석 결과 신규 일반공지 URL이 없는 구간에서도 다음 페이지 탐색이 계속됨 | 일반공지 항목이 있는 페이지에서 일반공지 신규 URL 0건이면 보드 수집 중단, 상시공지 전용 페이지는 예외 처리 | 초기 전체 수집 약 45분, 기존 증분 수집 약 3분 30초에서 약 1분 30초로 감소 |
| 본문 표/줄바꿈 Markdown 품질 | 빈 헤더 표(원본 헤더가 `<td>`)가 평문으로 뭉개지고, 공백 없이 붙은 번호 섹션 마커가 분리되지 않으며, 전화번호 닫는 괄호가 리스트 마커로 오인돼 끊김 | 빈 헤더 직사각형 데이터 표는 첫 행을 헤더로 승격해 표 유지, 흐름/레이아웃 표는 평문화 유지, 공백 없는 번호 마커 분리 보강, 전화번호 오분리 회귀 차단 | 입상자 명단 등 진짜 데이터 표가 Markdown 표로 렌더되고 번호 섹션이 줄 단위로 분리됨 |

## 상세 이력

### 1. 이미지/HWP/HWPX 기반 content 보강

문제 상황:

- 일부 공지는 본문 텍스트 없이 이미지, HWP, HWPX 첨부에 핵심 내용을 담습니다.
- 기본 fallback content만 저장하면 일정, 대상, 신청 방법, 제출 서류, 문의처가 검색/RAG 대상에 들어가지 않습니다.
- HWP/HWPX는 브라우저에서 바로 읽기 어렵고, 이미지 본문은 HTML 텍스트 파싱만으로 내용을 얻을 수 없습니다.

핵심 구현 로직:

- `CONTENT_ENRICHMENT_ENABLED=true`일 때 이미지/HWP/HWPX asset을 content 보강 후보로 분류합니다.
- 허용 도메인, 공개 IP, HTTP(S) 조건을 확인한 뒤 asset을 다운로드합니다.
- 이미지 본문과 이미지 첨부는 vision-capable provider로 텍스트를 추출합니다.
- HWPX는 ZIP/XML 직접 추출을 먼저 시도하고, HWP/HWPX는 `unhwp` 기반 로컬 추출을 사용합니다.
- 추출 텍스트와 공지 메타데이터를 LLM에 전달해 Markdown content를 생성합니다.
- 성공 시 기존 fallback은 `content_original`에 보존하고 생성 결과를 `content`에 반영합니다.

개선 결과:

- 검색 가능한 본문이 없던 공지도 일정, 대상, 방법, 제출 서류, 문의처 중심의 content를 가질 수 있습니다.
- 이미지/HWP/HWPX 중심 공지를 단순 실패나 placeholder가 아니라 후속 검색에 사용할 수 있는 공지로 유지합니다.

검증:

- 관련 코드: `app/crawler/services/content_enrichment_service.py`
- 상세 정책: [첨부/이미지 기반 content 보강](./09_content_enrichment_rules.md)
- 테스트: `tests/test_content_enrichment.py`

### 2. 증분 수집 페이지 탐색 병목 최적화

문제 상황:

- 일반공지는 최신순으로 정렬되는데도, 신규 공지가 없을 때 오래된 공지를 만날 때까지 다음 페이지를 계속 탐색했습니다.
- 증분 수집의 목적과 맞지 않게 불필요한 목록/상세 요청이 발생했습니다.
- 크롤링 로그 분석 결과, 일반공지 항목이 있는 페이지에서 일반공지 신규 URL이 0건인 경우에도 이후 페이지 탐색이 이어지는 병목이 확인됐습니다.
- 상시공지만 있는 페이지에서 단순히 신규 일반공지 0건만 보고 중단하면 다음 페이지의 일반공지를 놓칠 수 있습니다.

핵심 구현 로직:

- 현재 페이지에 일반공지 항목이 있고, 기존 URL 캐시에 없는 일반공지 신규 URL 수가 0이면 해당 보드 수집을 종료합니다.
- 같은 페이지에 신규 상시공지가 있으면 먼저 수집한 뒤 종료합니다.
- 상시공지만 있는 페이지는 이 조건으로 종료하지 않고 다음 페이지를 계속 확인합니다.
- 오래된 일반공지는 게시일이 파싱되고 `published_date <= cutoff_date`인 경우에만 중단 기준으로 사용합니다.

개선 결과:

- 신규 일반공지 구간까지만 탐색하므로 증분 수집 시간이 줄어듭니다.
- 운영 실측 예시는 초기 전체 수집 약 45분, 기존 증분 수집 약 3분 30초, 조건 추가 후 약 1분 30초입니다.
- 초기 전체 수집 대비 소요 시간은 약 96.7% 감소했고, 처리 시간 기준 약 30배 빠른 결과를 확인했습니다.
- 기존 증분 수집 3분 30초 대비로도 약 57.1% 추가 감소, 처리 시간 기준 약 2.3배 개선됐습니다.

검증:

- 관련 코드: `app/crawler/services/board_crawler.py`
- 관련 정책: `app/crawler/policies/notice_policy.py`
- 테스트:
  - `test_crawl_board_stops_when_page_has_no_new_general_items`
  - `test_crawl_board_collects_new_permanent_item_before_no_new_general_stop`
  - `test_crawl_board_continues_when_page_has_only_known_permanent_items`
- 관련 문서: [크롤링 규칙 상세](./08_crawling_rules.md)

### 3. 본문 표/줄바꿈 Markdown 품질 보정

문제 상황:

- 원본 HTML이 표 헤더를 `<th>`가 아니라 `<td>`로 만들면 markdownify가 빈 헤더 행을 생성합니다. ingest 정규화의 흐름 표 평문화 로직이 이런 표를 전부 공백 연결 평문으로 바꿔, 입상자 명단 같은 진짜 데이터 표가 한 문단으로 뭉쳐 렌더됐습니다.
- 원본 작성자가 `<br>` 없이 번호 섹션을 텍스트에 붙여 쓰면(`참조2. 강의기간`, `불가5.성적처리`, `(필독!!!)4. 학점`) 줄 단위로 분리되지 않았습니다. 기존 분리 정규식이 숫자 앞 공백과 마침표 뒤 공백을 모두 요구했기 때문입니다.
- 인라인 마커 분리 로직이 전화번호 닫는 괄호(`(02) 970`)를 `2)` 리스트 마커로 오인해 번호를 끊는 회귀가 있었습니다.

핵심 구현 로직:

- 빈 헤더 + 구분선 다음 데이터 행이 3열 이상, 2행 이상, 모든 행 칸 수가 같은 직사각형이고 화살표 단독 셀이 없으면 첫 행을 헤더로 승격해 Markdown 표로 유지합니다. 칸 수가 들쭉날쭉하거나 화살표가 든 흐름/공정 표는 기존대로 평문화합니다. (`app/normalize.py` `_normalize_flow_tables`, `_is_rectangular_data_table`)
- 직전이 한글/닫는 괄호/종결 부호이고 뒤가 `N. 한글` 형태일 때만 공백 없는 번호 섹션 마커를 줄바꿈으로 분리합니다. 날짜(`2026.06.09`)·소수·시간은 보호합니다. (`app/normalize.py` `INLINE_NUMBER_SECTION_RE`)
- 인라인 숫자 마커 분리 정규식의 직전 문자 집합에서 숫자를 제외해 전화번호 오분리를 차단합니다. (`app/crawler/utils/markdown_converter.py` `_NUMERIC_MARKER_RE`)

개선 결과:

- 입상자 명단 등 직사각형 데이터 표가 Markdown 표로 렌더되고, 번호 섹션이 줄 단위로 분리됩니다.
- 흐름/레이아웃 표 평문화와 날짜·전화번호 보존 동작은 그대로 유지됩니다.

참고:

- 프론트엔드 Markdown 렌더러는 단일 줄바꿈(`\n`)을 줄바꿈으로 표시하도록 `breaks`(GFM soft break) 옵션을 켜야 합니다. 백엔드는 항목을 단일 `\n`으로 분리하므로, 이 옵션이 꺼져 있으면 분리된 줄이 한 문단으로 합쳐져 보입니다.
- 기존에 게시된 JSON 스냅샷에는 과거 크롤 시점의 깨진 결과가 남아 있을 수 있고, 재크롤 후 ingest해야 보정 결과가 반영됩니다.

검증:

- 관련 코드: `app/normalize.py`, `app/crawler/utils/markdown_converter.py`
- 테스트:
  - `test_normalize_promotes_empty_header_data_table`
  - `test_normalize_flattens_empty_header_flow_table_with_arrows`
  - `test_normalize_splits_attached_number_section_markers`
  - `test_normalize_keeps_dates_intact`
  - `test_split_inline_markers_preserves_phone_numbers`

## 후속 기록 규칙

새 항목은 병목 해소 또는 고난도 task 해결에 해당하고, 실제 코드와 검증 근거가 있을 때만 추가합니다.

```markdown
### N. 제목

문제 상황:

- 어떤 병목 또는 고난도 task였는지

핵심 구현 로직:

- 문제를 해결한 구체적인 코드 경로 또는 알고리즘

개선 결과:

- 확인된 효과 또는 확인 가능한 기대 효과

검증:

- 관련 코드: `...`
- 테스트: `...`
```
