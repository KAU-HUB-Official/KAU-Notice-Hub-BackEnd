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

## 핵심 정책

- `requests + BeautifulSoup` 기반 크롤링
- 목록 단계에서 canonical URL 기준 중복 제거
- 기존 결과 파일(`--output` 경로)의 `original_url`을 캐시로 활용한 증분 수집
- 상세 단계에서 필수 필드(`title`, `content`) 검증
- 저장 전 URL 중복 + 제목 정규화 중복 통합

## 현재 제한

- 일부 게시글은 본문이 이미지 중심이라 텍스트가 충분하지 않을 수 있음
- 제목 기반 2차 중복 통합 시 동일 제목 공지가 하나로 합쳐질 수 있음
- `kau_eslscat` 구현은 존재하지만 기본 수집 목록에는 포함되지 않음
