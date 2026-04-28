# 아키텍처

## 디렉터리 역할

- `app/crawler/main.py`
  - 실행 인자 파싱, 전체 수집 오케스트레이션
  - 기존 결과 로드, 보드별 수집 호출, 중복 병합, 결과 저장
- `app/crawler/config.py`
  - 보드 목록(`NOTICE_BOARDS`)과 공통 상수(타임아웃, 지연, 출력 경로) 정의
- `app/crawler/clients/`
  - 사이트별 요청 URL 생성, 요청 실행, robots 검사, 지연 제어
- `app/crawler/parsers/`
  - 목록/상세 HTML(또는 JSON) 파싱
  - `is_permanent_notice` 판정, 본문/첨부/게시일 추출
- `app/crawler/services/`
  - `board_crawler.py`: 공통 보드 수집 엔진
  - `board_registry.py`: board_type별 client/parser/adapter 매핑
  - `post_store.py`: 기존 결과 로드
  - `dedup_service.py`: URL/제목 기준 병합
  - `url_normalizer.py`: canonical URL 정규화
- `app/crawler/policies/notice_policy.py`
  - 최근 1년 정책 및 상시공지 예외 처리
- `app/crawler/models/post.py`
  - 공통 `Post` 데이터 모델
- `app/crawler/utils/`
  - 로깅, JSON 저장

## 실행 흐름

1. `main.py`에서 클라이언트/어댑터를 생성
   - 생성 위치: `services/board_registry.py`
2. 결과 파일(`--output`)을 읽어 `known_urls` 캐시를 구성
   - `services/post_store.py` + `services/url_normalizer.py`
3. `NOTICE_BOARDS`를 순회하며 `crawl_board()` 실행
   - `services/board_crawler.py`
4. 목록 페이지를 순회하며 페이지별 상세 수집
   - canonical URL 기준으로 보드 내 중복 상세 요청 제거
   - 기존 URL은 상세 요청을 생략하되, 기존 `published_at`으로 일반공지 중단 여부 판단
5. 상세 수집 시 최근성 정책 적용
   - 상시공지: 항상 포함
   - 일반공지: 최근 365일만 포함, 기준 미충족 시 보드 수집 중단
6. 기존+신규 데이터를 최종 병합
   - URL 중복 제거
   - 제목 정규화 중복 통합 및 `source_meta` 누적
7. 결과/실패/로그 저장

## board_type 매핑

현재 레지스트리(`build_board_adapters`)의 주요 board_type:

- `kau_official`
- `kau_career`
- `kau_college`
- `kau_card_notice`
- `kau_research`
- `kau_admission`
- `kau_ctl`
- `kau_library`
- `kau_ftc`
- `kau_community_php`
- `kau_lms_ubboard`
- `kau_asbt`
- `kau_amtc`
- `kau_eslscat` (구현만 존재, 기본 보드 목록에는 미포함)

## 중복 제거 계층

- 1차: 목록/상세 수집 중 canonical `original_url` 중복 제거
- 2차: 최종 병합 시 canonical URL 기준 중복 제거
- 3차: 제목 정규화(공백 정리 + 소문자화) 기준 중복 통합

제목 중복 통합 시:

- `source_name`, `source_type`, `category_raw`를 배열로 병합
- 상세 출처 정보는 `source_meta` 배열에 누적
- 첨부파일은 URL 기준으로 병합

## 요청 및 페이지 정책

- 공통 `requests.Session` 사용
- `REQUEST_TIMEOUT_SECONDS=15`
- 요청 간 랜덤 지연(`REQUEST_DELAY_SECONDS=(0.5, 1.2)`)
- robots 기본 준수 (`kau_career`만 예외)
- `--max-pages 0`은 페이지 상한 없이 최근성 정책으로 자동 중단
- `--max-pages N`은 보드별 최대 N페이지까지만 순회하며, `min_pages`가 있으면 더 큰 값을 사용
- `max_posts`는 현재 상세 수집 상한으로 직접 사용되지 않으며, 일부 보드의 페이지 단위(`page_unit`) 설정에 활용
