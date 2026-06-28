"""레이트리밋 동작 검증.

운영 app 싱글턴은 인메모리 카운터를 공유하므로, 한도 초과 동작은 격리된 별도
FastAPI app + 자체 Limiter로 검증한다. client_ip 키 함수와 429 응답 형태도 확인한다.
"""

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.datastructures import Headers

from app.config import get_settings
from app.rate_limit import client_ip, rate_limit_exceeded_handler


def _make_request(headers: dict[str, str], client_host: str | None) -> Request:
    scope = {
        "type": "http",
        "headers": Headers(headers).raw,
        "client": (client_host, 12345) if client_host else None,
    }
    return Request(scope)


def test_client_ip_prefers_x_real_ip() -> None:
    request = _make_request({"x-real-ip": "203.0.113.7"}, "127.0.0.1")
    assert client_ip(request) == "203.0.113.7"


def test_client_ip_falls_back_to_connection_ip() -> None:
    request = _make_request({}, "198.51.100.4")
    assert client_ip(request) == "198.51.100.4"


def test_client_ip_trusts_forwarded_only_with_valid_token(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_PROXY_TOKEN", "secret-123")
    get_settings.cache_clear()
    try:
        # 토큰 일치 → BFF가 넘긴 실제 브라우저 IP(X-Client-IP)를 쓴다.
        ok = _make_request(
            {
                "x-internal-token": "secret-123",
                "x-client-ip": "1.2.3.4",
                "x-real-ip": "9.9.9.9",
            },
            "127.0.0.1",
        )
        assert client_ip(ok) == "1.2.3.4"

        # 토큰 불일치 → X-Client-IP 무시, Caddy의 X-Real-IP로 폴백(스푸핑 차단).
        bad = _make_request(
            {
                "x-internal-token": "wrong",
                "x-client-ip": "1.2.3.4",
                "x-real-ip": "9.9.9.9",
            },
            "127.0.0.1",
        )
        assert client_ip(bad) == "9.9.9.9"
    finally:
        monkeypatch.delenv("INTERNAL_PROXY_TOKEN", raising=False)
        get_settings.cache_clear()


def test_client_ip_ignores_forwarded_when_no_token_configured(monkeypatch) -> None:
    monkeypatch.delenv("INTERNAL_PROXY_TOKEN", raising=False)
    get_settings.cache_clear()
    try:
        # 토큰 미설정(기본) → 전달 IP를 신뢰하지 않고 X-Real-IP를 쓴다.
        request = _make_request(
            {"x-internal-token": "whatever", "x-client-ip": "1.2.3.4", "x-real-ip": "9.9.9.9"},
            "127.0.0.1",
        )
        assert client_ip(request) == "9.9.9.9"
    finally:
        get_settings.cache_clear()


def _build_limited_app() -> TestClient:
    app = FastAPI()
    limiter = Limiter(key_func=client_ip, enabled=True)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    @app.get("/ping")
    @limiter.limit("2/minute")
    async def ping(request: Request) -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


def test_rate_limit_blocks_after_threshold() -> None:
    client = _build_limited_app()
    headers = {"x-real-ip": "203.0.113.9"}

    assert client.get("/ping", headers=headers).status_code == 200
    assert client.get("/ping", headers=headers).status_code == 200

    blocked = client.get("/ping", headers=headers)
    assert blocked.status_code == 429
    # 내부 상세를 노출하지 않고 일반화된 한국어 메시지만 반환한다.
    assert blocked.json() == {"error": "요청이 너무 많습니다. 잠시 후 다시 시도해주세요."}


def test_rate_limit_is_per_ip() -> None:
    client = _build_limited_app()

    # 한 IP가 한도를 소진해도 다른 IP는 영향받지 않는다.
    for _ in range(3):
        client.get("/ping", headers={"x-real-ip": "203.0.113.10"})

    other = client.get("/ping", headers={"x-real-ip": "203.0.113.11"})
    assert other.status_code == 200


def _build_shared_limit_app() -> TestClient:
    """같은 scope의 shared_limit을 건 두 엔드포인트(실제 chat/chat_stream 구성과 동일)."""
    app = FastAPI()
    limiter = Limiter(key_func=client_ip, enabled=True)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    @app.get("/a")
    @limiter.shared_limit("2/minute", scope="grp")
    async def a(request: Request) -> dict[str, bool]:
        return {"ok": True}

    @app.get("/b")
    @limiter.shared_limit("2/minute", scope="grp")
    async def b(request: Request) -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


def test_shared_limit_pools_across_endpoints() -> None:
    """같은 scope의 두 엔드포인트는 한 버킷을 공유한다(엔드포인트별 분리 우회 방지)."""
    client = _build_shared_limit_app()
    headers = {"x-real-ip": "203.0.113.20"}

    assert client.get("/a", headers=headers).status_code == 200
    assert client.get("/b", headers=headers).status_code == 200
    # 두 엔드포인트 합산이 한도(2/분)에 도달 → 다음 요청은 어느 쪽이든 429
    assert client.get("/a", headers=headers).status_code == 429
