"""主数据-供应商接口（§8.2）。

端点：GET /suppliers（列表）、POST /suppliers（新建）。
权限点：master:supplier:read / master:supplier:write（默认角色 admin, ops）。
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
from app.schema.store import SupplierCreate, SupplierOut, SupplierPage

router = APIRouter()

IdempotencyKey = Annotated[
    str | None, Header(alias="Idempotency-Key", max_length=64, description="幂等键，≤64 字符")
]


@router.get("", response_model=ApiResponse[SupplierPage], summary="供应商列表")
def list_suppliers(
    db: DbSession,
    pagination: Pagination,
    user: CurrentUser,
    service: MasterService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.SUPPLIER_READ))],
    keyword: Annotated[str | None, Query(max_length=64, description="编码/名称模糊搜索")] = None,
    status_filter: Annotated[int | None, Query(alias="status", ge=0, le=1)] = None,
) -> ApiResponse[SupplierPage]:
    """GET /suppliers：分页返回供应商。"""
    result = service.list_suppliers(
        db,
        page=pagination.page,
        page_size=pagination.page_size,
        keyword=keyword,
        status=status_filter,
    )
    data = SupplierPage(
        list=[SupplierOut.model_validate(item) for item in result.items],
        total=result.total,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return ok(data)


@router.post("", response_model=ApiResponse[SupplierOut], summary="新建供应商")
def create_supplier(
    payload: SupplierCreate,
    db: DbSession,
    user: CurrentUser,
    service: MasterService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.SUPPLIER_WRITE))],
    idempotency_key: IdempotencyKey = None,
) -> ApiResponse[SupplierOut]:
    """POST /suppliers：新建供应商；重复提交同一 supplier_no 返回首次结果。"""
    supplier = service.create_supplier(
        db, payload, operator_id=user.get("user_id"), idempotency_key=idempotency_key
    )
    return ok(SupplierOut.model_validate(supplier))
