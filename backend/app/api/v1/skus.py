"""主数据-SKU 接口（§8.2）。

端点：GET /skus（列表/筛选）、POST /skus（新建）。
权限点：master:sku:read / master:sku:write（默认角色 admin, ops）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query

from app.core.deps import (
    CurrentUser,
    DbSession,
    MasterService,
    Pagination,
    PermissionCode,
    require_permission,
)
from app.schema.common import ApiResponse, ok
from app.schema.store import SkuCreate, SkuOut, SkuPage

router = APIRouter()

IdempotencyKey = Annotated[
    str | None, Header(alias="Idempotency-Key", max_length=64, description="幂等键，≤64 字符")
]


@router.get("", response_model=ApiResponse[SkuPage], summary="SKU 列表/筛选")
def list_skus(
    db: DbSession,
    pagination: Pagination,
    user: CurrentUser,
    service: MasterService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.SKU_READ))],
    category: Annotated[str | None, Query(max_length=32, description="品类精确筛选")] = None,
    keyword: Annotated[str | None, Query(max_length=64, description="编码/品名模糊搜索")] = None,
    status_filter: Annotated[int | None, Query(alias="status", ge=0, le=1)] = None,
) -> ApiResponse[SkuPage]:
    """GET /skus：按品类/关键字/状态筛选并分页。"""
    result = service.list_skus(
        db,
        page=pagination.page,
        page_size=pagination.page_size,
        category=category,
        keyword=keyword,
        status=status_filter,
    )
    data = SkuPage(
        list=[SkuOut.model_validate(item) for item in result.items],
        total=result.total,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return ok(data)


@router.post("", response_model=ApiResponse[SkuOut], summary="新建 SKU")
def create_sku(
    payload: SkuCreate,
    db: DbSession,
    user: CurrentUser,
    service: MasterService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.SKU_WRITE))],
    idempotency_key: IdempotencyKey = None,
) -> ApiResponse[SkuOut]:
    """POST /skus：单位/换算/保质期一次落齐；重复提交同一 sku_no 返回首次结果。"""
    sku = service.create_sku(
        db, payload, operator_id=user.get("user_id"), idempotency_key=idempotency_key
    )
    return ok(SkuOut.model_validate(sku))
