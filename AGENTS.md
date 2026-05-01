# AGENTS.md

## 범위

이 문서는 `KAU-Notice-Hub-BackEnd` 저장소 전체에 적용되는 에이전트 작업 규칙이다.

이 프로젝트는 KAU Notice Hub의 FastAPI 백엔드다. 공지 데이터는 JSON 전체 스냅샷으로 제공하고, 내장 크롤러가 주기적으로 데이터를 갱신하며, 운영 배포는 Docker Compose, Caddy, GitHub Actions, Lightsail을 기준으로 한다.

## 프로젝트 구조

| 경로 | 역할 |
| --- | --- |
| `app/` | FastAPI 앱, 서비스 계층, repository, schemas, 검색, 크롤러 스케줄러 |
| `app/crawler/` | 내장 KAU 공지 크롤러 |
| `scripts/run_incremental_crawl_publish.sh` | 수동 증분 크롤링 및 atomic JSON 게시 스크립트 |
| `tests/` | Pytest 테스트 |
| `docs/` | API, 크롤러, 분류, ERD, 배포 문서 |
| `.github/workflows/ci.yml` | 테스트 workflow |
| `.github/workflows/deploy.yml` | Lightsail 배포 workflow |
| `docker-compose.yml` | API, crawler tool profile, Caddy reverse proxy 구성 |
| `Caddyfile` | Caddy reverse proxy 설정 |

## 작업 원칙

동작이 바뀌는 작업은 아래 순서로 진행한다.

1. 관련 코드와 기존 문서를 먼저 읽는다.
2. 크롤러 정책, API 계약, 배포, 운영 방식이 바뀌면 구현 전에 계획 또는 문서를 먼저 정리한다.
3. 기존 구조에 맞춰 가장 좁은 범위로 구현한다.
4. 변경 범위에 맞는 테스트를 추가하거나 수정한다.
5. 테스트를 실행한다.
6. 최초 문서와 실제 구현이 달라졌다면 문서를 다시 정리한다.

문서만 변경하는 경우에도 최소한 `git diff --check`를 실행한다.

## 재질문 기준

사용자 지시가 모호하면 임의로 단정하지 않는다. 특히 변경 범위, 대상 파일, 배포 여부, 데이터 삭제 여부, 보안 설정처럼 결과가 달라질 수 있는 지점은 작업 전에 짧게 재질문한다.

다만 기존 코드와 문서에서 의도를 명확히 추론할 수 있고, 변경 위험이 낮으며, 되돌리기 쉬운 작업은 합리적인 가정을 명시하고 진행할 수 있다.

판단이 필요한 상황이면서 결과가 크리티컬하면 반드시 멈추고 확인한다. 아래 경우는 재질문 대상이다.

- 운영 데이터 삭제, 대량 변경, 복구가 어려운 마이그레이션
- secret, SSH key, 인증, 권한, 방화벽, 배포 경로 변경
- `main` 직접 push, 강제 push, history rewrite 등 Git 이력에 영향을 주는 작업
- 외부 공개 포트, CORS, 도메인, HTTPS 등 보안 경계 변경
- API 계약 변경처럼 frontend 또는 외부 사용자에게 영향을 주는 변경
- 크롤러 삭제 정책, 중복 제거 기준, 데이터 보존 기준 변경
- 비용이 발생하거나 클라우드 리소스 상태를 바꾸는 작업

재질문할 때는 선택지를 길게 늘리지 말고, 확인해야 할 핵심 결정만 간단히 묻는다.

## 기본 명령

개발 의존성 설치:

```bash
python3 -m pip install -e '.[dev]'
```

테스트:

```bash
pytest
```

로컬 API 실행:

```bash
uvicorn app.main:app --reload --port 8000
```

수동 크롤링 1회 실행:

```bash
NOTICE_JSON_PATH=./data/kau_official_posts.json \
bash scripts/run_incremental_crawl_publish.sh
```

Docker Compose 실행:

```bash
docker compose up -d --build api
docker compose --profile proxy up -d --build
docker compose ps
```

## 코드 작업 규칙

- 현재 FastAPI, Pydantic, JSON repository, service layer 구조를 유지한다.
- 새 추상화를 만들기보다 기존 helper와 schema를 우선 사용한다.
- API 응답에 내부 예외 상세, 파일 시스템 경로, secret 값을 노출하지 않는다.
- 클라이언트 응답을 일반화해야 하는 오류는 서버 로그에만 상세를 남긴다.
- API 응답 형태는 `docs/API_SPEC.md`와 호환되게 유지한다.
- 크롤러 동작은 `docs/CRAWLING_UPDATE.md`와 `docs/crawler/` 문서와 맞춘다.
- 사용자가 명시적으로 요구하지 않는 한 Redis, Celery, DB, 별도 worker 구조를 추가하지 않는다.
- 좁은 버그 수정 중에는 광범위한 리팩터링을 피한다.

## 크롤러 규칙

API는 `NOTICE_JSON_PATH`를 현재 전체 공지 스냅샷으로 읽는다. 증분 수집을 하더라도 최종 게시 파일은 병합된 전체 스냅샷이어야 한다.

크롤러 게시 로직은 아래 규칙을 지켜야 한다.

- 기존 전체 스냅샷을 읽는다.
- 신규, 최근, 변경 가능성이 있는 공지를 수집한다.
- 기존 공지와 새 공지를 병합한다.
- 기존 코드의 URL, id, 제목/날짜 정책 등 안정적인 기준으로 중복 제거한다.
- 1년 이상 지난 상시공지가 아닌 공지는 최종 병합 스냅샷 정책 안에서만 제거한다.
- 상시공지는 게시일과 무관하게 유지한다.
- 날짜를 파싱할 수 없는 공지는 1년 초과 조건을 확정할 수 없으면 삭제하지 않는다.
- 먼저 임시 파일에 쓴다.
- 새 JSON을 검증한 뒤 live 파일을 교체한다.
- live 파일 교체는 atomic 방식으로 수행한다.
- 검증 실패 시 기존 live 파일을 유지한다.

## 배포 규칙

`main`은 배포 브랜치다.

기본 흐름:

1. 작업 브랜치에서 수정한다.
2. Pull request를 만든다.
3. GitHub Actions `test` 통과를 확인한다.
4. `main`에 merge한다.
5. GitHub Actions가 Lightsail에 자동 배포한다.

개인 운영 프로젝트라 organization admin bypass를 허용할 수 있다. PR 흐름을 우회해 `main`에 직접 push할 때도 코드 변경이면 로컬에서 `pytest`를 먼저 실행한다.

배포 workflow는 Lightsail 서버에 접속해 아래 명령을 실행한다.

```bash
cd ~/KAU-Notice-Hub-BackEnd
git pull origin main
docker compose --profile proxy up -d --build
docker compose ps
```

운영 기준:

- 외부 공개 진입점은 Caddy의 `80`, `443` 포트다.
- API 컨테이너의 host `8000` 포트는 `127.0.0.1`에만 바인딩한다.
- Lightsail 방화벽에서 TCP `8000`은 열지 않는다.
- `API_DOMAIN`이 Caddy site 주소를 결정한다.
- 도메인이 없으면 `API_DOMAIN=:80`으로 HTTP-only 접근을 허용할 수 있다.

## Secret 및 로컬 데이터

절대 커밋하지 않는다.

- `.env`, `.env.*`. 단, `.env.example`은 예외
- SSH private key
- `lightsail_deploy_key*`
- `*.pem`
- `*.key`
- `data/` 아래의 로컬 JSON 스냅샷
- 로그와 프로세스 파일

GitHub 배포 secret:

| Secret | 의미 |
| --- | --- |
| `LIGHTSAIL_HOST` | Lightsail 공인 IPv4 또는 DNS 이름 |
| `LIGHTSAIL_USER` | 보통 `ubuntu` |
| `LIGHTSAIL_SSH_KEY` | 배포용 private key 전체 |

private key가 노출되면 새 key로 교체하고, GitHub Secrets를 갱신하고, 새 public key를 서버 `~/.ssh/authorized_keys`에 추가한 뒤, 기존 public key를 서버에서 제거한다.

## 문서 갱신 기준

아래 영역을 변경하면 관련 문서를 함께 갱신한다.

| 변경 | 문서 |
| --- | --- |
| API 요청/응답 계약 | `docs/API_SPEC.md` |
| source group, category, audience 분류 | `docs/CLASSIFICATION.md` |
| 크롤러 병합, 오래된 공지 삭제, 게시 정책 | `docs/CRAWLING_UPDATE.md`, `docs/crawler/` |
| 배포, 방화벽, Caddy, GitHub Actions, secrets | `docs/DEPLOYMENT.md` |
| 저장 JSON 형태 또는 논리 엔티티 | `docs/ERD.md` |
| 주요 명령 또는 빠른 시작 변경 | `README.md` |

사용자가 명시적으로 요구하지 않는 한 제거된 확장 관련 기록이나 계획을 다시 추가하지 않는다.

## 검증 체크리스트

코드 변경을 마치기 전:

```bash
pytest
git diff --check
git status --short
```

배포 관련 변경이면 추가 확인:

```bash
docker compose config
```

로컬에서 Docker를 사용할 수 없으면 실행하지 못했다고 명시하고 YAML은 리뷰로 확인한다.
