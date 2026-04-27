# BackEnd 문서

KAU Notice Hub 독립 백엔드 개발/운영 문서 모음이다.

## 문서 목록
| 문서 | 내용 |
| --- | --- |
| [BACKEND_STRUCTURE_PLAN.md](BACKEND_STRUCTURE_PLAN.md) | 백엔드 구조 설계 계획 |
| [ERD.md](ERD.md) | MVP JSON 논리 모델, 향후 PostgreSQL ERD, 사용자/알림 확장 모델 |
| [API_SPEC.md](API_SPEC.md) | 공지 목록/상세/챗봇/헬스체크 API 계약 |
| [CRAWLING_UPDATE.md](CRAWLING_UPDATE.md) | 증분 크롤링, 전체 JSON 스냅샷 갱신, atomic 교체 정책 |
| [DEPLOYMENT.md](DEPLOYMENT.md) | VPS+Docker Compose 기반 백엔드 배포 계획 |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | FastAPI MVP 구현 순서, 테스트 계획, 완료 기준 |

## MVP 기준 결정
초기 백엔드는 아래 원칙으로 구현한다.

- FastAPI 서버
- JSON 파일 저장소
- 외부 스케줄러 기반 주기 크롤링
- 증분 수집 + 전체 JSON 스냅샷 교체
- 프론트 API 계약 유지
- PostgreSQL, 로그인, 맞춤형 공지, 키워드 알림은 이후 확장

## 개발 순서
개발은 [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)의 단계별 계획을 따른다.

우선순위:

1. FastAPI skeleton
2. JSON 정규화/repository
3. 분류/검색/필터링
4. 공지 API
5. 챗봇 fallback API
6. 크롤링 갱신 스크립트
7. Docker 배포 구성
8. 프론트 API URL 전환
