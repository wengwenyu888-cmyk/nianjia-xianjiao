"""健康检查接口。

- GET /api/v1/health            存活探针：不依赖任何外部组件，永远 200
- GET /api/v1/health/readiness  就绪探针：额外探测数据库连通性
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings
from app.schema.common import ApiResponse, ok

router = APIRouter(tags=["health"])


@router.get("/health", response_model=ApiResponse[dict], summary="存活探针")
def health() -> ApiResponse[dict]:
    """容器存活探针：进程活着即返回 200，不查数据库。"""
    return ok({"status": "ok", "app": settings.APP_NAME, "version": settings.VERSION})


@router.get("/health/readiness", response_model=ApiResponse[dict], summary="就绪探针")
def readiness() -> ApiResponse[dict]:
    """就绪探针：数据库不可用时返回 degraded，供负载均衡摘流量。"""
    from app.service.health_service import check_database

    db_ok = check_database()
    return ok({"status": "ok" if db_ok else "degraded", "database": "up" if db_ok else "down"})
