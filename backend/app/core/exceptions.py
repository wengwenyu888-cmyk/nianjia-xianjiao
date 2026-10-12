"""统一业务异常 + 全局异常处理器。

要点：对外错误响应绝不包含堆栈与 SQL；业务异常由 service 层主动抛出 BusinessError。
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)


class BusinessError(Exception):
    """业务异常基类：service 层主动抛出，由处理器转成统一响应体。"""

    code: int = 40000
    http_status: int = status.HTTP_400_BAD_REQUEST
    message: str = "业务处理失败"

    def __init__(self, message: str | None = None, *, code: int | None = None) -> None:
        self.message = message or self.message
        if code is not None:
            self.code = code
        super().__init__(self.message)


class NotFoundError(BusinessError):
    """资源不存在。"""

    code = 40400
    http_status = status.HTTP_404_NOT_FOUND
    message = "资源不存在"


class PermissionDeniedError(BusinessError):
    """越权访问（含门店账号访问他人门店数据）。"""

    code = 40300
    http_status = status.HTTP_403_FORBIDDEN
    message = "无权限访问该资源"


class ConflictError(BusinessError):
    """状态冲突 / 重复提交（幂等键冲突）。"""

    code = 40900
    http_status = status.HTTP_409_CONFLICT
    message = "数据状态冲突，请刷新后重试"


def _body(code: int, message: str, data: Any = None) -> dict[str, Any]:
    """构造统一响应体。"""
    return {"code": code, "message": message, "data": data}


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器（FastAPI 按异常类型精确匹配）。"""

    @app.exception_handler(BusinessError)
    async def _business_error_handler(request: Request, exc: BusinessError) -> JSONResponse:
        logger.warning("业务异常 %s %s -> %s", request.method, request.url.path, exc.message)
        return JSONResponse(status_code=exc.http_status, content=_body(exc.code, exc.message))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "请求处理失败"
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(exc.status_code * 100, detail),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # 参数校验错误只回字段与原因，不回原始请求体（可能含敏感信息）
        errors = [
            {"field": ".".join(str(x) for x in item.get("loc", [])), "reason": item.get("msg", "")}
            for item in exc.errors()
        ]
        # 对齐 docs/02 §8.1 错误码分段：参数校验失败统一 40000 / HTTP 400
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=_body(40000, "请求参数校验失败", errors),
        )

    @app.exception_handler(Exception)
    async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        # 不向外返回堆栈与 SQL，只在服务端留日志
        logger.exception("未处理异常 %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_body(50000, "服务内部错误，请稍后重试或联系管理员"),
        )
