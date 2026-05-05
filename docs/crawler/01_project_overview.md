# 프로젝트 개요

## 목적

한국항공대학교 분산 공지 게시판을 단일 스키마(`Post`)로 수집하는 통합 크롤러입니다.

## 현재 범위

기본 설정(`app/crawler/config.py`의 `NOTICE_BOARDS`) 기준 수집 대상은 다음과 같습니다.

- `kau.ac.kr` 공식 공지 7종
- `career.kau.ac.kr` 대학일자리센터 공지 1종
- `college.kau.ac.kr` 계열 공지 42종
- `aisw.kau.ac.kr`, `ai.kau.ac.kr`, `sw.kau.ac.kr`, `ave.kau.ac.kr` 카드형 학과/대학 공지 8종
- `research.kau.ac.kr` 산학협력단 공지 1종
- `ibhak.kau.ac.kr` 입학처 공지 1종
- `ctl.kau.ac.kr` 교수학습센터 공지 1종
- `lib.kau.ac.kr` 학술정보관 공지 1종
- `ftc.kau.ac.kr` 비행교육원 공지 1종
- `amtc.kau.ac.kr` 항공기술교육원 공지 1종
- `fsc.kau.ac.kr`, `grad.kau.ac.kr`, `gradbus.kau.ac.kr` 공통 PHP 공지 3종
- `lms.kau.ac.kr` LMS 공지 1종
- `asbt.kau.ac.kr` 첨단분야 부트캠프사업단 공지 1종

총 69개 보드를 기본 수집합니다.

## 수집 데이터 포맷

`app/crawler/models/post.py`의 `Post` 모델 필드:

- `source_name`
- `source_type`
- `category_raw`
- `title`
- `content`
- `published_at`
- `original_url`
- `attachments`
- `crawled_at`
- `content_assets`

최종 JSON 스냅샷에는 수집/병합/보강 단계에서 아래 metadata가 추가될 수 있습니다.

- `is_permanent_notice`
- `source_meta`
- `content_original`
- `content_enrichment`
- `summary`

## 핵심 정책

- `requests + BeautifulSoup` 기반 크롤링
- 목록 단계에서 canonical URL 기준 중복 제거
- 기존 결과 파일(`--output` 경로)의 `original_url`을 캐시로 활용한 증분 수집
- 상세 단계에서 필수 필드(`title`, `content`) 검증
- 본문 이미지/동영상/첨부파일만 있는 공지는 fallback content로 보존
- 저장 전 URL 중복 + 제목 정규화 중복 통합
- `CONTENT_ENRICHMENT_ENABLED=true`이면 이미지/HWP/HWPX 기반 content 보강

## 현재 제한

- content 보강은 기본값이 꺼져 있으므로, 운영에서 켜기 전까지 이미지/HWP 중심 공지는 fallback content로 남을 수 있음
- 동영상 iframe만 있는 공지는 최소 정보만 보존하며 영상 내용이나 자막은 추출하지 않음
- 제목 기반 2차 중복 통합 시 동일 제목 공지가 하나로 합쳐질 수 있음
