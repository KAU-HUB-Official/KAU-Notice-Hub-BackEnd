import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.notices import router as notices_router
from app.config import get_settings
from app.crawler_scheduler import run_crawler_scheduler
from app.rate_limit import limiter, rate_limit_exceeded_handler

logger = logging.getLogger("app.main")


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
    app = FastAPI(
        title="KAU Notice Hub BackEnd",
        version="0.1.0",
        lifespan=lifespan,
    )

    # 레이트리밋: 라우트의 @limiter.limit 데코레이터가 app.state.limiter를 참조하고,
    # 한도 초과 시 RateLimitExceeded를 일반화된 429 JSON으로 변환한다.
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

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
    return app


app = create_app()
