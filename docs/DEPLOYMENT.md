# 백엔드 배포 계획

## 범위
이 문서는 KAU Notice Hub 독립 백엔드의 배포 구성을 정의한다.

초기 MVP 배포 목표:

- 백엔드는 독립 FastAPI 서버로 배포한다.
- 초기 저장소는 JSON 파일을 사용한다.
- 크롤러는 백엔드 API 서버와 분리해 주기 실행한다.
- HTTPS, CORS, 환경변수, 데이터 파일 경로를 명확히 관리한다.

프론트엔드 Vercel 배포는 [MVP/docs/DEPLOYMENT.md](../../MVP/docs/DEPLOYMENT.md)에서 관리한다.

## 권장 MVP 배포 구조
```text
외부 프론트엔드
  -> https://api.example.com/api/notices

VPS
  -> Caddy 또는 Nginx
  -> FastAPI API container
  -> shared data volume: /data/kau_official_posts.json
  -> crawler cron/container
```

MVP에서는 **VPS + Docker Compose** 구성을 우선 권장한다.

이유:

- API 서버와 크롤러가 같은 JSON 파일을 안정적으로 공유하기 쉽다.
- `/data` 같은 디렉토리를 Docker volume으로 관리하면 구조가 단순하다.
- cron 또는 별도 crawler container를 붙이기 쉽다.
- PostgreSQL 도입 전까지 PaaS의 파일 공유 제약을 피할 수 있다.

## 구성 요소
| 구성 요소 | 역할 | MVP 권장 배포 위치 |
| --- | --- | --- |
| FastAPI backend | 공지 API, 챗봇 API | VPS Docker container |
| Crawler | 증분 수집 및 JSON 갱신 | VPS cron 또는 crawler container |
| JSON data file | MVP 공지 저장소 | VPS shared volume |
| Caddy/Nginx | HTTPS reverse proxy | VPS Docker container 또는 host |

## 도메인 구성
권장 도메인:

```text
백엔드 API: https://api.kau-notice.example.com
```

프론트엔드 도메인은 백엔드 CORS 허용 origin에만 반영한다.

## 백엔드 배포
백엔드는 FastAPI Docker container로 실행한다.

개발 실행:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

MVP 운영 실행:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

트래픽이 늘거나 안정성이 필요하면 Gunicorn + Uvicorn worker로 전환한다.

```bash
gunicorn app.main:app \
  -k uvicorn.workers.UvicornWorker \
  -w 2 \
  -b 0.0.0.0:8000
```

초기에는 worker 수를 크게 늘리지 않는다. JSON 파일 캐시를 각 worker가 따로 들 수 있으므로, 데이터 크기와 메모리를 보고 조정한다.

## 백엔드 환경변수
| 이름 | 예시 | 설명 |
| --- | --- | --- |
| `NOTICE_JSON_PATH` | `/data/kau_official_posts.json` | API 서버가 읽는 전체 공지 JSON 스냅샷 |
| `BACKEND_CORS_ORIGINS` | `https://kau-notice.example.com` | 허용할 프론트엔드 origin |
| `OPENAI_API_KEY` | `sk-...` | 선택. 챗봇 OpenAI 응답 활성화 |
| `OPENAI_MODEL` | `gpt-4.1-mini` | 선택. 챗봇 모델명 |
| `LOG_LEVEL` | `INFO` | 선택. 로그 레벨 |

로컬 개발 예시:

```env
NOTICE_JSON_PATH=./data/kau_official_posts.json
BACKEND_CORS_ORIGINS=http://localhost:3000
OPENAI_MODEL=gpt-4.1-mini
```

운영 예시:

```env
NOTICE_JSON_PATH=/data/kau_official_posts.json
BACKEND_CORS_ORIGINS=https://kau-notice.example.com,https://kau-notice.vercel.app
OPENAI_MODEL=gpt-4.1-mini
```

## Docker Compose 구성 초안
아래는 구현 시 사용할 수 있는 구성 방향이다.

```yaml
services:
  api:
    build:
      context: .
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
    env_file:
      - .env
    volumes:
      - notice_data:/data
    expose:
      - "8000"
    restart: unless-stopped

  crawler:
    build:
      context: ../Crawler
    env_file:
      - .env
    volumes:
      - notice_data:/data
    profiles:
      - tools

  caddy:
    image: caddy:2
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      - api
    restart: unless-stopped

volumes:
  notice_data:
  caddy_data:
  caddy_config:
```

실제 파일 경로와 build context는 백엔드 레포 분리 방식에 맞춰 조정한다.

## Reverse Proxy
Caddy 예시:

```text
api.kau-notice.example.com {
  reverse_proxy api:8000
}
```

Nginx를 사용해도 된다. MVP에서는 HTTPS 인증서 자동 관리가 쉬운 Caddy가 단순하다.

## 크롤러 주기 실행
크롤러는 API 서버 내부에서 실행하지 않는다.

권장 방식:

```text
cron 또는 scheduler
  -> crawler container 실행
  -> 기존 JSON 스냅샷과 증분 수집 결과 병합
  -> tmp JSON 검증
  -> /data/kau_official_posts.json atomic 교체
```

상세 정책은 [CRAWLING_UPDATE.md](CRAWLING_UPDATE.md)를 따른다.

cron 예시:

```cron
*/60 * * * * cd /opt/kau-notice-backend && docker compose run --rm crawler ./scripts/run_incremental_crawl_publish.sh
```

## 배포 순서
1. 백엔드 서버에 Docker와 Docker Compose 설치
2. 백엔드 레포 clone
3. `.env` 작성
4. `/data` 또는 Docker volume 준비
5. 초기 공지 JSON 생성
6. `docker compose up -d --build`
7. `GET /health` 확인
8. `GET /api/notices` 확인
9. Caddy/Nginx 도메인 연결
10. cron 또는 crawler scheduler 설정
11. 프론트엔드 배포 문서에 따라 API URL 연결 확인

## 헬스 체크
필수 확인:

```bash
curl https://api.kau-notice.example.com/health
```

예상 응답:

```json
{
  "status": "ok"
}
```

추후 운영 지표가 필요하면 아래 필드를 추가한다.

```json
{
  "status": "ok",
  "storage": "json",
  "noticeCount": 1250,
  "lastLoadedAt": "2026-04-27T10:20:30+09:00",
  "sourceUpdatedAt": "2026-04-27T10:18:02+09:00"
}
```

## CORS 확인
프론트 도메인에서 API 호출이 실패하면 먼저 CORS 설정을 확인한다.

필수 조건:

- `BACKEND_CORS_ORIGINS`에 프론트엔드 production domain 포함
- preview 배포를 테스트한다면 preview domain도 포함
- credentials가 필요한 로그인 기능 도입 전까지는 단순 origin 허용으로 충분

## 로그 확인
확인할 로그:

```bash
docker compose logs -f api
docker compose logs -f crawler
docker compose logs -f caddy
```

운영에서 반드시 확인할 이벤트:

- JSON 로드 성공/실패
- JSON 재로드 성공/실패
- 크롤러 실행 시작/종료
- 크롤러 결과 검증 실패
- API 500 에러

## 장애 대응 기준
| 상황 | 대응 |
| --- | --- |
| API 서버 다운 | `docker compose ps`, `docker compose logs api`, container restart 확인 |
| JSON 파싱 실패 | 기존 정상 캐시 유지 여부 확인, 크롤러 tmp 파일 검증 |
| 크롤링 실패 | 기존 JSON 유지, crawler 로그 확인 |
| CORS 에러 | `BACKEND_CORS_ORIGINS`와 프론트엔드 도메인 확인 |
| 프론트에서 API 호출 실패 | 백엔드 HTTPS 상태와 프론트 API base URL 확인 |
| 데이터가 갱신되지 않음 | cron 실행 여부, JSON mtime, `/health` 확장 필드 확인 |

## PostgreSQL 전환 후 배포 변화
PostgreSQL을 도입하면 JSON 공유 volume 의존도가 줄어든다.

변경 후 구조:

```text
Crawler scheduler
  -> 신규/수정 공지 수집
  -> DB upsert

FastAPI
  -> PostgreSQL 조회
  -> API 응답
```

이 단계에서는 다음 선택지가 가능하다.

- VPS + Docker Compose + PostgreSQL container
- Managed PostgreSQL
- Railway/Fly.io/DigitalOcean App Platform 같은 PaaS

MVP에서는 먼저 JSON 기반 배포를 안정화하고, 운영 필요성이 생기면 PostgreSQL로 전환한다.
