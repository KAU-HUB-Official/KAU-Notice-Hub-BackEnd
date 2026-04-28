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
- `required_field_empty`: `title` 누락 또는 `content` 누락이며 첨부파일 fallback도 불가능한 경우
- `robots_disallowed`: robots 정책으로 요청 차단
- `missing_ntt_id`: `kau_college` 상세 URL에서 `nttId` 누락
- `missing_notice_id`: `kau_eslscat` 상세 URL에서 `id` 누락

참고: `missing_notice_id`는 `kau_eslscat` 보드를 활성화한 경우에만 발생 가능합니다.

## 기본 점검 루틴

1. `crawler.log`에서 보드별 `collected/new` 로그 확인
2. 최종 저장 로그의 `newly_added`, `url_dedup_removed`, `title_dedup_removed` 확인
3. 실패 파일의 `reason`별 건수 확인
4. 문제 URL 샘플 재현(브라우저/직접 요청)로 원인 분리

## 자주 보는 케이스

- `kau_career`: robots 예외 정책이 적용되어 robots 차단 없이 수집
- 이미지 중심 본문: 텍스트 대신 이미지 fallback 문자열 저장
- 첨부파일만 있는 본문: 첨부파일명 기반 fallback 문자열 저장
- 대학 사이트 개편: 목록 selector 변경으로 `request_failed`가 아니라 `new=0` 패턴으로 먼저 나타나는 경우가 많음

## 중복/증분 관련 동작

- 기존 결과 파일을 URL 캐시로 사용해 재수집 오버헤드 절감
- canonical URL로 정규화해 `page/search` 차이 중복 제거
- URL 중복 제거 후 제목 정규화 기준으로 교차 사이트 재게시 공지 통합
- 페이지 순회는 오래된 일반공지/빈 목록/반복 목록을 만날 때 종료

## 증분 수집 실측 결과

- 최종 저장 게시글 수: 2,229건
- 초기 전체 수집 소요 시간: 약 45분(2,700초)
- 증분 수집 소요 시간: 약 3분 30초(210초)
- 소요 시간 기준 개선률: 약 92.2% 감소
- 처리 시간 배율: 약 12.9배 빠름

계산식:

- 개선률 = `(2,700초 - 210초) / 2,700초 * 100 = 92.2%`
- 배율 = `2,700초 / 210초 = 12.9배`

## 운영 팁

- 구조 점검용 스모크 테스트는 `--max-pages 1`로 제한하고, 실제 수집은 기본 실행(`--max-pages 0`)을 사용
- 사이트 구조가 변경되면 parser와 문서(`05_parsing_and_selectors.md`)를 함께 갱신
- 정책 변경 시 `notice_policy.py`, `board_crawler.py`, `08_crawling_rules.md`를 같이 수정
