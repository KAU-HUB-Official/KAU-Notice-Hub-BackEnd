import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from app.api.auth import router as auth_router
from app.api.bookmarks import router as bookmarks_router
from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.notices import router as notices_router
from app.auth import (
    AuthenticationRequired,
    authentication_required_handler,
    user_store_error_handler,
)
from app.config import get_settings
from app.crawler_scheduler import run_crawler_scheduler
from app.rate_limit import limiter, rate_limit_exceeded_handler
from app.user_store import UserStoreError

logger = logging.getLogger("app.main")


def configure_app_logging(level: str) -> None:
    """app.* 로거를 LOG_LEVEL로 출력한다.

    uvicorn은 자기 로거(uvicorn.*)만 설정하므로, 그대로 두면 app.* 로그는 WARNING 이상만
    보이고 ingest 결과 같은 INFO 로그가 운영 로그에 남지 않는다. 루트 로거는 건드리지 않아
    openai/httpx 같은 라이브러리 로그는 늘어나지 않는다.
    """
    app_logger = logging.getLogger("app")
    resolved = logging.getLevelName(level.strip().upper())
    app_logger.setLevel(resolved if isinstance(resolved, int) else logging.INFO)
    if not app_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s %(message)s"))
        app_logger.addHandler(handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    scheduler_task: asyncio.Task[None] | None = None

    if settings.crawler_scheduler_enabled:
        scheduler_task = asyncio.create_task(run_crawler_scheduler(settings))
        app.state.crawler_scheduler_task = scheduler_task
        logger.info("crawler scheduler enabled")
    else:
        logger.info("crawler scheduler disabled")

    try:
        yield
    finally:
        if scheduler_task:
            scheduler_task.cancel()
            await asyncio.gather(scheduler_task, return_exceptions=True)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_app_logging(settings.log_level)
    app = FastAPI(
        title="KAU Notice Hub BackEnd",
        version="0.1.0",
        lifespan=lifespan,
    )

    # 레이트리밋: 라우트의 @limiter.limit 데코레이터가 app.state.limiter를 참조하고,
    # 한도 초과 시 RateLimitExceeded를 일반화된 429 JSON으로 변환한다.
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    # 로그인 필수 의존성(get_current_user)의 실패를 기존 ErrorResponse 형식으로 바꾼다.
    app.add_exception_handler(AuthenticationRequired, authentication_required_handler)
    app.add_exception_handler(UserStoreError, user_store_error_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(notices_router)
    app.include_router(chat_router)
    app.include_router(auth_router)
    app.include_router(bookmarks_router)
    return app


app = create_app()
