"""FastAPI 应用入口。

职责：建 app、注册中间件（CORS / 限流）、挂载 /api/v1 路由、注册全局异常处理器。
约定：本文件只做「装配」，不写任何业务逻辑。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.rate_limit import limiter

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """启动 / 关闭钩子：骨架阶段只打日志，后续放连接池预热、定时任务注册。"""
    setup_logging()
    logger.info("应用启动：%s v%s（env=%s）", settings.APP_NAME, settings.VERSION, settings.ENV)
    yield
    logger.info("应用关闭：%s", settings.APP_NAME)


def register_rate_limit_handler(application: FastAPI) -> None:
    """把 slowapi 的 429 转成与项目一致的统一响应体。"""
    from slowapi.errors import RateLimitExceeded
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    @application.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={"code": 42900, "message": "请求过于频繁，请稍后重试", "data": None},
        )


def create_app() -> FastAPI:
    """按环境变量装配 FastAPI 实例（工厂模式，便于测试中重复创建）。"""
    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.VERSION,
        description="念家鲜饺供应链总部 API：要货 → 汇总 → 分拣 → 配送 → 签收 → 对账",
        lifespan=lifespan,
        # 生产环境关闭交互式文档（见 docs/05 安全要点）
        docs_url="/docs" if settings.is_dev else None,
        redoc_url="/redoc" if settings.is_dev else None,
        openapi_url=None if settings.is_prod else "/openapi.json",
    )

    # 跨域：白名单显式枚举，禁止 allow_origins=["*"] 搭配 allow_credentials=True
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
    )

    # 限流：slowapi 可用时挂到 app.state（与业务装饰器共用同一实例）
    if limiter is not None:
        application.state.limiter = limiter
        register_rate_limit_handler(application)

    # 统一异常处理器：错误响应不外泄堆栈与 SQL
    register_exception_handlers(application)

    # 业务路由统一挂在 /api/v1 下
    application.include_router(api_router, prefix=settings.API_V1_PREFIX)

    return application


app = create_app()
