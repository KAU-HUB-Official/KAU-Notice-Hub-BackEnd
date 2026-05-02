# 문서 인덱스

이 디렉터리는 KAU Notice Hub 크롤러 문서를 주제별로 분리한 안내서입니다.
아래 문서는 현재 코드(`app/crawler/`) 기준으로 정리되어 있습니다.

## 문서 목록

1. [프로젝트 개요](./01_project_overview.md)
2. [실행 가이드](./02_quickstart.md)
3. [크롤링 대상](./03_crawl_targets.md)
4. [아키텍처](./04_architecture.md)
5. [파싱 규칙과 셀렉터](./05_parsing_and_selectors.md)
6. [운영/장애 대응](./06_operations_and_failure.md)
7. [크롤링 규칙 상세](./08_crawling_rules.md)
8. [첨부/이미지 기반 content 보강 계획](./09_content_enrichment_plan.md)

## 권장 읽기 순서

- 처음 파악할 때: `01 -> 02 -> 03`
- 구조/코드 매핑이 필요할 때: `04 -> 05`
- 운영 모니터링/장애 대응: `06 -> 08`
- 본문이 비어 있는 공지 보강 설계: `09`

## 관련 경로

- 엔트리포인트: `app/crawler/main.py`
- 설정: `app/config.py`, `app/crawler/config.py`
- 보드 수집 엔진: `app/crawler/services/board_crawler.py`
- 보드 타입 레지스트리: `app/crawler/services/board_registry.py`
- 수집 정책: `app/crawler/policies/notice_policy.py`
- content 보강: `app/crawler/services/content_enrichment_service.py`
- 결과 산출물 디렉터리: `data/`
