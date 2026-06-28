"""Per-IP 요청 레이트리밋 (slowapi, 인메모리).

운영에서 API 컨테이너는 127.0.0.1에만 바인딩되고 외부 진입은 Caddy 한 곳뿐이다.
Caddy가 신뢰 가능한 `X-Real-IP`(실제 peer 주소)를 set 한다(Caddyfile의 `header_up`
참고). 따라서 클라이언트 식별은 `X-Real-IP`를 우선 신뢰하고, 없으면(로컬 직접 호출 등)
연결 IP로 폴백한다. 클라이언트가 보낸 `X-Real-IP`는 Caddy의 `header_up`이 덮어쓰므로
스푸핑되지 않는다.

uvicorn 워커가 2개라 인메모리 카운터는 워커별로 적용돼 실효 한도가 약 2배가 되지만,
연타성 어뷰징/비용 폭주 차단에는 충분하다. AGENTS.md의 "Redis 등 외부 인프라 금지"
원칙에 맞춰 외부 저장소 없이 프로세스 메모리만 쓴다.

한도 값은 설정(`RATE_LIMIT_CHAT`, `RATE_LIMIT_NOTICES`)에서 읽고, 비활성화는
`RATE_LIMIT_ENABLED=false`로 한다(테스트 기본값은 비활성).
"""

from __future__ import annotations

import secrets

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import get_settings


def client_ip(request: Request) -> str:
    """레이트리밋 버킷 키 = 가능한 한 '실제 사용자' IP.

    우선순위:
      1) BFF(Vercel)가 신뢰 토큰과 함께 넘긴 실제 브라우저 IP(X-Client-IP).
         X-Internal-Token이 INTERNAL_PROXY_TOKEN과 일치할 때만 신뢰한다.
         (BFF 프록시 구조에선 직접 안 넘기면 모든 사용자가 Vercel IP 하나로 묶인다.)
      2) Caddy가 set한 X-Real-IP — 백엔드를 직접 때리는 요청의 실제 peer.
         Caddy의 header_up이 덮어쓰므로 클라이언트가 스푸핑할 수 없다.
      3) 연결 IP(로컬 직접 호출 등).
    """
    settings = get_settings()
    token = settings.internal_proxy_token
    if token:
        provided = request.headers.get("x-internal-token")
        # 타이밍 공격 방지를 위해 상수 시간 비교.
        if provided and secrets.compare_digest(provided, token):
            forwarded = request.headers.get("x-client-ip")
            if forwarded:
                return forwarded.split(",")[0].strip()

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.split(",")[0].strip()
    return get_remote_address(request)


def chat_rate_limit(*_args: object) -> str:
    """`/api/chat`(+stream) 한도. 요청 1건이 OpenAI를 여러 번 호출하므로 빡빡하게."""
    return get_settings().rate_limit_chat


def notices_rate_limit(*_args: object) -> str:
    """`/api/notices` 한도. 단순 DB 읽기라 느슨하게."""
    return get_settings().rate_limit_notices


limiter = Limiter(
    key_func=client_ip,
    enabled=get_settings().rate_limit_enabled,
)


def rate_limit_exceeded_handler(request: Request, exc: Exception) -> JSONResponse:
    """한도 초과 응답. 내부 상세(한도 문자열 등)는 숨기고 일반화 메시지만 반환한다."""
    return JSONResponse(
        status_code=429,
        content={"error": "요청이 너무 많습니다. 잠시 후 다시 시도해주세요."},
    )
