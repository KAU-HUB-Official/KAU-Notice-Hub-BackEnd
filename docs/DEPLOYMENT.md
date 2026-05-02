# 백엔드 배포

## 범위
이 문서는 KAU Notice Hub FastAPI 백엔드의 로컬 실행과 Docker Compose 배포 기준을 정의한다.

현재 MVP 구성:

- FastAPI API 서버
- JSON 파일 저장소
- `app/crawler`에 포함된 크롤러와 API 프로세스 내 백그라운드 스케줄러
- 공유 데이터 volume의 `/data/kau_official_posts.json`
- 선택적 Caddy reverse proxy
- GitHub Actions 기반 Lightsail 자동 배포

## 로컬 실행

의존성 설치:

```bash
python3 -m pip install -e '.[dev]'
```

서버 실행:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

확인:

```bash
curl http://localhost:8000/health
curl 'http://localhost:8000/api/notices?page=1&pageSize=5'
```

API 문서 UI:

```text
http://localhost:8000/docs
http://localhost:8000/redoc
http://localhost:8000/openapi.json
```

## 환경변수

| 이름 | 예시 | 설명 |
| --- | --- | --- |
| `NOTICE_JSON_PATH` | `/data/kau_official_posts.json` | API 서버가 읽는 전체 공지 JSON 스냅샷 |
| `BACKEND_CORS_ORIGINS` | `https://kau-notice.example.com` | 쉼표로 구분한 허용 frontend origin |
| `BACKEND_PORT` | `8000` | Docker host에 바인딩할 API 포트. compose에서는 `127.0.0.1`에만 바인딩 |
| `API_DOMAIN` | `api.kau-notice.example.com` 또는 `:80` | Caddy가 받을 host. 도메인이 없으면 `:80` |
| `OPENAI_API_KEY` | `sk-...` | content 보강에서 OpenAI provider를 사용할 때 필요. 챗봇은 현재 local fallback 사용 |
| `OPENAI_MODEL` | `gpt-4.1-mini` | 챗봇용 예약값. 현재 챗봇은 local fallback 사용 |
| `CONTENT_ENRICHMENT_ENABLED` | `false` | 본문이 비어 있는 이미지/HWP 공지의 content 보강 활성화 |
| `CONTENT_ENRICHMENT_PROVIDER` | `openai` | content 보강 provider |
| `CONTENT_ENRICHMENT_MODEL` | `gpt-4.1-mini` | 이미지 텍스트 추출과 content 생성 기본 모델 |
| `CONTENT_ENRICHMENT_FALLBACK_MODEL` | `gpt-5.5` | 이미지 텍스트가 부족할 때 재시도할 fallback 모델 |
| `CONTENT_ENRICHMENT_IMAGE_DETAIL` | `high` | OpenAI 이미지 입력 detail 값 |
| `CONTENT_ENRICHMENT_MIN_TEXT_LENGTH` | `30` | 이 길이 미만의 fallback/짧은 본문만 보강 후보로 판단 |
| `CONTENT_ENRICHMENT_MAX_ASSETS_PER_NOTICE` | `3` | 공지 1건에서 처리할 최대 이미지/HWP asset 수 |
| `CONTENT_ENRICHMENT_MAX_FILE_BYTES` | `10485760` | 다운로드할 asset 최대 크기 |
| `CONTENT_ENRICHMENT_MAX_CALLS_PER_RUN` | `50` | crawl 1회당 보강 API 호출 상한 |
| `CONTENT_ENRICHMENT_ALLOWED_DOMAINS` | `kau.ac.kr,...` | asset 다운로드를 허용할 도메인 allowlist |
| `LOG_LEVEL` | `INFO` | 로그 레벨 |
| `CRAWLER_SCHEDULER_ENABLED` | `true` | API 프로세스 내 크롤러 스케줄러 활성화 |
| `CRAWLER_INTERVAL_SECONDS` | `10800` | 크롤링 주기. 기본 3시간 |
| `CRAWLER_RUN_ON_STARTUP` | `true` | 서버 시작 직후 1회 크롤링 |
| `CRAWLER_MAX_PAGES` | `0` | 게시판별 목록 페이지 상한. 0이면 최근성 정책으로 자동 중단 |
| `CRAWLER_MIN_RECORDS` | `1` | 게시 허용 최소 레코드 수 |
| `CRAWLER_MIN_RETAIN_RATIO` | `0.5` | 기존 개수 대비 급감 방어 비율 |

로컬 예시:

```env
NOTICE_JSON_PATH=./data/kau_official_posts.json
BACKEND_CORS_ORIGINS=http://localhost:3000
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
CONTENT_ENRICHMENT_ENABLED=false
CONTENT_ENRICHMENT_PROVIDER=openai
CONTENT_ENRICHMENT_MODEL=gpt-4.1-mini
CONTENT_ENRICHMENT_FALLBACK_MODEL=gpt-5.5
CONTENT_ENRICHMENT_IMAGE_DETAIL=high
CONTENT_ENRICHMENT_MIN_TEXT_LENGTH=30
CONTENT_ENRICHMENT_MAX_ASSETS_PER_NOTICE=3
CONTENT_ENRICHMENT_MAX_FILE_BYTES=10485760
CONTENT_ENRICHMENT_MAX_CALLS_PER_RUN=50
LOG_LEVEL=INFO
CRAWLER_SCHEDULER_ENABLED=false
CRAWLER_INTERVAL_SECONDS=10800
CRAWLER_RUN_ON_STARTUP=true
```

운영 서버의 `.env`는 서버에만 둔다. `.env`, SSH private key, `.pem`, `.key` 파일은 저장소에 커밋하지 않는다.

`OPENAI_API_KEY`나 `CONTENT_ENRICHMENT_*` 값을 서버 `.env`에서 바꾼 뒤에는 컨테이너를 재생성해야 반영된다.

```bash
docker compose --profile proxy up -d --build --force-recreate api
```

## Docker Compose

구현 파일은 [../docker-compose.yml](../docker-compose.yml)이다.

API만 실행:

```bash
docker compose up -d --build api
```

API와 Caddy reverse proxy 실행:

```bash
docker compose --profile proxy up -d --build
```

운영 compose에서는 API 컨테이너 포트를 host의 `127.0.0.1:8000`에만 바인딩한다. 외부 사용자는 8000 포트로 직접 접근하지 않고 Caddy의 80/443을 통해 접근한다.

```text
api
  -> 127.0.0.1:8000 only
caddy
  -> public 80/443
  -> reverse_proxy api:8000
```

Docker Compose 서비스 종료:

```bash
docker compose down
```

로컬에서 `uvicorn`을 직접 실행 중이면 해당 터미널에서 `Ctrl+C`로 종료한다. 백그라운드 실행 중인 로컬 서버는 아래 명령으로 종료할 수 있다.

```bash
pkill -f "uvicorn app.main:app"
```

크롤러 1회 실행:

```bash
docker compose --profile tools run --rm crawler
```

현재 compose 구성의 핵심:

```text
api
  -> reads /data/kau_official_posts.json
  -> runs bundled app/crawler scheduler every 10800 seconds
  -> writes /data/kau_official_posts.json atomically

crawler
  -> optional one-off/manual tool profile
  -> runs scripts/run_incremental_crawl_publish.sh
  -> writes /data/kau_official_posts.json atomically
  -> runs bundled app/crawler package

caddy
  -> reverse_proxy api:8000
```

## 원격 서버 준비

권장 환경은 Ubuntu 계열 Lightsail/VPS다.

서버에 필요한 항목:

- Docker
- Docker Compose plugin
- Git
- 이 저장소 clone
- 서버 전용 `.env`
- GitHub Actions 배포용 SSH public key 등록

Lightsail 방화벽 기준:

| 포트 | 공개 여부 | 설명 |
| --- | --- | --- |
| `22/tcp` | 필요 | SSH 접속과 GitHub Actions 배포용. 가능하면 접속원을 제한한다. GitHub-hosted runner는 IP가 변동될 수 있다. |
| `80/tcp` | 공개 | Caddy HTTP 진입점 |
| `443/tcp` | 공개 | Caddy HTTPS 진입점. 도메인을 쓰면 Caddy가 인증서를 발급한다. |
| `8000/tcp` | 비공개 | API 직접 접근 포트. Lightsail 방화벽에서 열지 않는다. |

도메인을 쓰는 경우 DNS에서 `api.example.com`의 A 레코드를 서버 공인 IP로 연결하고 서버 `.env`에 `API_DOMAIN=api.example.com`을 둔다. 도메인이 없으면 `API_DOMAIN=:80`으로 HTTP만 사용할 수 있다.

## GitHub Actions 배포

현재 자동 배포는 [../.github/workflows/deploy.yml](../.github/workflows/deploy.yml)을 따른다.

트리거:

- `main` 브랜치에 push 또는 merge

실행 내용:

```bash
cd ~/KAU-Notice-Hub-BackEnd
git pull origin main
docker compose --profile proxy up -d --build
docker compose ps
```

Repository secrets:

| 이름 | 값 |
| --- | --- |
| `LIGHTSAIL_HOST` | 서버 공인 IPv4 또는 도메인 |
| `LIGHTSAIL_USER` | Ubuntu Lightsail 기본값은 보통 `ubuntu` |
| `LIGHTSAIL_SSH_KEY` | 배포용 SSH private key 전체. `-----BEGIN OPENSSH PRIVATE KEY-----`부터 `-----END OPENSSH PRIVATE KEY-----`까지 포함 |

배포용 SSH key 기준:

- private key는 GitHub Secret에만 저장한다.
- public key는 서버의 `~/.ssh/authorized_keys`에 한 줄로 추가한다.
- private key 파일은 저장소에 커밋하지 않는다.
- 노출된 key는 새 key로 교체하고 서버 `authorized_keys`에서 제거한다.

## 브랜치 운영

기본 운영 흐름:

1. 작업 브랜치에서 수정
2. Pull request 생성
3. GitHub Actions `test` 통과 확인
4. `main`에 merge
5. deploy workflow가 자동 배포

개인 운영에서 organization admin bypass를 허용한 경우 `main` 직접 push도 가능하다. 이 경우에도 코드 변경 전에는 로컬에서 `pytest`를 실행하고, push 후 GitHub Actions 결과와 서버 상태를 확인한다.

```bash
pytest
git push origin main
```

## 데이터 파일 준비

스케줄러가 활성화되어 있으면 API 컨테이너 시작 직후 1회 크롤링해 `NOTICE_JSON_PATH`를 만든다. 첫 크롤링이 끝나기 전 목록 API는 JSON 파일이 없어 500을 반환할 수 있으므로, 배포 직후에는 로그에서 첫 publish 완료를 확인한다.

로컬:

```bash
mkdir -p data
cp ../MVP/kau_official_posts.json data/kau_official_posts.json
```

Docker volume을 미리 채우고 싶다면 crawler tool profile을 한 번 실행하거나, 운영 서버에서 volume 내부에 초기 JSON을 넣는다.

## 크롤러 주기 실행

크롤러는 API 요청 처리 경로에서 실행하지 않고, FastAPI lifespan에서 시작한 백그라운드 task가 주기 실행한다. 기본 Docker Compose 설정은 3시간마다 실행한다.

수동 1회 실행이 필요할 때:

```bash
docker compose --profile tools run --rm crawler
```

스크립트 상세 정책은 [CRAWLING_UPDATE.md](CRAWLING_UPDATE.md)를 따른다.

## 최초 배포 순서

1. Lightsail/VPS 생성
2. 방화벽에서 `22`, `80`, `443`만 허용하고 `8000`은 열지 않음
3. Docker, Docker Compose plugin, Git 설치
4. 서버에 백엔드 레포 clone
5. 서버 `~/.ssh/authorized_keys`에 배포용 SSH public key 추가
6. GitHub Repository secrets에 `LIGHTSAIL_HOST`, `LIGHTSAIL_USER`, `LIGHTSAIL_SSH_KEY` 등록
7. 서버 프로젝트 루트에 `.env` 작성
8. 서버에서 `docker compose --profile proxy up -d --build` 1회 수동 실행
9. `docker compose ps`에서 `api`가 `127.0.0.1:8000->8000/tcp`, `caddy`가 `80/443`으로 뜨는지 확인
10. `curl http://localhost:8000/health` 또는 `curl https://api.example.com/health` 확인
11. GitHub Actions deploy workflow를 한 번 실행해 자동 배포 확인
12. frontend의 API base URL 전환
13. `docker compose logs -f api`에서 crawler publish 완료 확인

## 수동 배포

GitHub Actions를 쓰지 않고 서버에서 직접 배포할 때:

```bash
cd ~/KAU-Notice-Hub-BackEnd
git pull origin main
docker compose --profile proxy up -d --build
docker compose ps
```

배포 후 `api` 포트가 아래처럼 `127.0.0.1`에만 묶여 있어야 한다.

```text
127.0.0.1:8000->8000/tcp
```

## 운영 확인

필수 확인:

```bash
curl https://api.kau-notice.example.com/health
curl 'https://api.kau-notice.example.com/api/notices?page=1&pageSize=5'
```

문서 UI:

```text
https://api.kau-notice.example.com/docs
https://api.kau-notice.example.com/redoc
https://api.kau-notice.example.com/openapi.json
```

로그:

```bash
docker compose logs -f api
docker compose logs -f caddy
```

## 장애 대응 기준

| 상황 | 확인 |
| --- | --- |
| API 서버 다운 | `docker compose ps`, `docker compose logs api` |
| JSON 파싱 실패 | crawler tmp 검증 로그, API 이전 정상 캐시 유지 여부 |
| 크롤링 실패 | `docker compose logs api`, 기존 JSON 유지 여부 |
| CORS 에러 | `BACKEND_CORS_ORIGINS`와 frontend origin |
| 데이터 미갱신 | `CRAWLER_SCHEDULER_ENABLED`, JSON mtime, API repository reload |
| Swagger 미노출 | `/docs`, `/openapi.json` 응답 상태 |
