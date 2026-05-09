# 운영/장애 대응

## 로그와 산출물

- 실행 로그: `data/crawler.log`
- 성공 데이터: `data/kau_official_posts.json`
- 실패 데이터: `data/kau_official_failed.json`

참고:

- 실행 시 `--output`을 변경하면 성공 데이터 경로도 함께 변경됩니다.
- 실패 항목이 0건이면 기존 `kau_official_failed.json` 파일은 삭제됩니다.

## 실패 reason 정의

- `request_failed`: HTTP 요청 실패, 타임아웃, 네트워크 오류
- `parse_error:<Exception>`: 상세 파싱 중 예외
- `required_field_empty:<fields>`: `title` 또는 `content` 누락. 예: `required_field_empty:content`, `required_field_empty:title,content`
  - 실패 항목에는 `missing_fields` 배열도 함께 기록한다.
  - `content` 누락은 본문 이미지/동영상/첨부파일 fallback도 불가능한 경우에만 실패로 기록한다.
- `robots_disallowed`: robots 정책으로 요청 차단
- `missing_ntt_id`: `kau_college` 상세 URL에서 `nttId` 누락

## content 보강 실패 코드

`CONTENT_ENRICHMENT_ENABLED=true`인 경우 이미지/HWP/HWPX 기반 본문 보강 실패는 크롤링 실패로 보지 않는다. 해당 공지는 기존 fallback `content`를 유지하고 `content_enrichment.status=failed`와 `error_code`만 기록한다.

공지 1건에 여러 asset이 있으면 asset 단위로 처리한다. 일부 asset 다운로드나 텍스트 추출이 실패해도 즉시 공지 전체를 실패로 확정하지 않고, 남은 asset을 계속 시도한다. 하나 이상의 asset에서 텍스트를 얻고 최종 content 생성까지 성공하면 해당 공지는 `success`가 된다. 모든 처리 가능한 asset에서 사용할 텍스트를 얻지 못하면 `no_extracted_text`로 실패한다.

- `missing_openai_api_key`: OpenAI provider를 쓰도록 설정했지만 `OPENAI_API_KEY`가 없음
- `unsafe_asset_url`: 허용 도메인/공개 IP/HTTP(S) 조건을 만족하지 않는 asset URL
- `unsafe_asset_redirect`: 다운로드 중 허용되지 않은 URL로 redirect
- `asset_download_failed`: asset 다운로드 HTTP 오류
- `asset_too_large`: `CONTENT_ENRICHMENT_MAX_FILE_BYTES` 초과
- `unsupported_asset_type`: 이미지/HWP/HWPX로 판별할 수 없음
- `hwp_text_extractor_unavailable`: HWP 추출 라이브러리 사용 불가
- `password_protected_hwp`: 암호화된 HWP
- `unsupported_hwp_format`: 미지원 또는 손상된 HWP/HWPX
- `hwp_text_extract_failed`: HWP 텍스트 추출 실패
- `hwp_text_too_short`: 추출 텍스트가 최소 길이 미만
- `image_text_too_short`: 이미지에서 추출된 텍스트가 최소 길이 미만
- `openai_request_failed`: OpenAI API 요청 실패
- `openai_invalid_response`: OpenAI 응답이 JSON 형식이 아님
- `openai_empty_response`: OpenAI 응답 텍스트가 비어 있음
- `llm_json_parse_failed`: content 생성 응답 JSON 파싱 실패
- `generated_content_too_short`: 생성된 content가 최소 길이 미만
- `no_extracted_text`: 처리한 asset에서 사용할 텍스트를 얻지 못함

## content 보강 skip reason

- `enrichment_call_budget_exceeded`: crawl 1회 호출 상한 초과. 실패가 아니라 비용 방어로 인한 보류 상태다. 해당 공지는 `content_enrichment.status=skipped`로 기록하고 다음 실행에서 다시 시도할 수 있게 둔다.

## content 보강 로그 해석

완료 로그 예시:

```text
본문 보강 | 시도=184 | 성공=4 | 실패=180 | 건너뜀=2068 | 호출=10
```

- `시도`: 보강 후보로 판정되어 실제 성공/실패 판정까지 진행한 공지 수. 예산 소진으로 `skipped`된 공지는 포함하지 않는다.
- `성공`: 최종 `content` 생성에 성공해 `content_enrichment.status=success`가 된 공지 수
- `실패`: 보강을 시도했지만 사용할 텍스트 추출이나 최종 content 생성에 실패한 공지 수
- `건너뜀`: 보강 대상이 아니거나 호출 예산 소진으로 이번 실행에서 처리하지 않은 공지 수
- `호출`: 이번 crawl에서 OpenAI 기반 이미지 추출 또는 content 생성에 사용한 호출 수

`성공`이 적다고 해서 자동 재시작 로직이 동작했다는 뜻은 아니다. 호출 예산, asset 다운로드 실패, HWP 추출 실패, 이미지 텍스트 부족 등이 섞인 결과일 수 있다. 원인은 JSON의 `content_enrichment.error_code`, `asset_errors`, `reason`을 함께 확인한다.

목록 수집 로그 예시:

```text
목록 | 게시판=일반공지 | 페이지=1 | 전체=10 | 신규=2 | 상시공지=1 | 일반공지=9 | 신규일반공지=2
수집 종료 | 게시판=일반공지 | 사유=신규 일반공지 없음 | 페이지=2
```

- `전체`: 목록에서 파싱한 항목 수
- `신규`: 기존 URL 캐시에 없는 항목 수. 상시공지와 일반공지를 모두 포함한다.
- `상시공지`: 목록에서 상시공지로 판정한 항목 수
- `일반공지`: 목록에서 일반공지로 판정한 항목 수
- `신규일반공지`: 기존 URL 캐시에 없는 일반공지 수. `일반공지`가 1건 이상이고 이 값이 0이면 같은 페이지의 신규 상시공지 처리 후 보드 수집을 종료한다. `일반공지=0`인 상시공지 전용 페이지는 이 조건으로 중단하지 않는다.

## 기본 점검 루틴

1. `crawler.log`에서 보드별 `전체`, `신규`, `상시공지`, `일반공지`, `신규일반공지` 로그 확인
2. 최종 저장 로그의 `전체`, `신규`, `URL중복`, `제목중복`, `오래된공지삭제` 확인
3. content 보강 완료 로그의 `시도`, `성공`, `실패`, `건너뜀`, `호출` 확인
4. 실패 파일의 `reason`별 건수 확인
5. content 보강 실패는 게시 JSON의 `content_enrichment.error_code`, `asset_errors`, `reason` 확인
6. 문제 URL 샘플 재현(브라우저/직접 요청)로 원인 분리

## 자주 보는 케이스

- `kau_career`: robots 예외 정책이 적용되어 robots 차단 없이 수집
- 이미지 중심 본문: 기본값은 이미지 fallback 문자열 저장. content 보강이 켜져 있으면 본문 이미지에서 텍스트 추출 후 `content` 교체 시도
- 동영상 중심 본문: 기본값은 동영상 fallback 문자열 저장. 현재 content 보강 대상은 아니며 URL/제목 수준의 최소 정보만 보존
- 첨부파일만 있는 본문: 기본값은 첨부파일명 기반 fallback 문자열 저장. content 보강이 켜져 있으면 이미지/HWP/HWPX 첨부에서 텍스트 추출 후 `content` 교체 시도
- 대학 사이트 개편: 목록 selector 변경으로 `request_failed`가 아니라 `전체=0` 또는 `신규=0` 패턴으로 먼저 나타나는 경우가 많음

## 중복/증분 관련 동작

- 기존 결과 파일을 URL 캐시로 사용해 재수집 오버헤드 절감
- canonical URL로 정규화해 `page/search` 차이 중복 제거
- URL 중복 제거 후 제목 정규화 기준으로 교차 사이트 재게시 공지 통합
- 페이지 순회는 일반공지 항목이 있는 페이지의 신규 일반공지 URL 0건/오래된 일반공지/빈 목록/반복 목록을 만날 때 종료
- 병합 후 1년 이상 지난 일반공지는 최종 스냅샷에서 제거
- 레코드 급감 방어는 오래된 일반공지를 제외한 기존 보존 대상 건수를 기준으로 계산

## 증분 수집 실측 예시

- 초기 전체 수집 소요 시간: 약 45분(2,700초)
- 기존 증분 수집 소요 시간: 약 3분 30초(210초)
- 일반공지 신규 URL 0건 조건 추가 후 증분 수집 소요 시간: 약 1분 30초(90초)
- 초기 전체 수집 대비 소요 시간 기준 개선률: 약 96.7% 감소
- 초기 전체 수집 대비 처리 시간 배율: 약 30배 빠름
- 기존 증분 수집 대비 추가 개선률: 약 57.1% 감소, 약 2.3배 빠름

위 수치는 특정 시점의 운영 실측값입니다. 현재 저장 건수는 `data/kau_official_posts.json` 기준으로 다시 확인합니다.

계산식:

- 초기 전체 수집 대비 개선률 = `(2,700초 - 90초) / 2,700초 * 100 = 96.7%`
- 초기 전체 수집 대비 배율 = `2,700초 / 90초 = 30배`
- 기존 증분 수집 대비 추가 개선률 = `(210초 - 90초) / 210초 * 100 = 57.1%`
- 기존 증분 수집 대비 배율 = `210초 / 90초 = 2.3배`

## 운영 팁

- 구조 점검용 스모크 테스트는 `--max-pages 1`로 제한하고, 실제 수집은 기본 실행(`--max-pages 0`)을 사용
- 사이트 구조가 변경되면 parser와 문서(`05_parsing_and_selectors.md`)를 함께 갱신
- 정책 변경 시 `notice_policy.py`, `board_crawler.py`, `08_crawling_rules.md`를 같이 수정
- content 보강 정책 변경 시 `content_enrichment_service.py`, `content_asset_downloader.py`, `content_extractors/`, `09_content_enrichment_rules.md`를 같이 수정
