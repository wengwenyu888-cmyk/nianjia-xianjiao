"""主数据-门店接口（§8.2）。

端点：GET /stores（分页列表）、POST /stores（新建）、PUT /stores/{id}（修改）。
权限点：master:store:read / master:store:write（默认角色 admin；查询另含 ops）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Path, Query

from app.core.deps import (
    CurrentUser,
    DbSession,
    MasterService,
    Pagination,
    PermissionCode,
    require_permission,
)
from app.schema.common import ApiResponse, ok
from app.schema.store import StoreCreate, StoreOut, StorePage, StoreUpdate

router = APIRouter()

# 幂等请求头（§8.1，≤64 字符）；主数据表无 idempotency_key 列，
# 由 service 以 uk_store_no 等业务唯一索引兜底：同键同体返回首次结果，同键异体 40900。
IdempotencyKey = Annotated[
    str | None, Header(alias="Idempotency-Key", max_length=64, description="幂等键，≤64 字符")
]


@router.get("", response_model=ApiResponse[StorePage], summary="门店分页列表")
def list_stores(
    db: DbSession,
    pagination: Pagination,
    user: CurrentUser,
    service: MasterService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.STORE_READ))],
    keyword: Annotated[str | None, Query(max_length=64, description="编码/名称模糊搜索")] = None,
    status_filter: Annotated[int | None, Query(alias="status", ge=0, le=1)] = None,
) -> ApiResponse[StorePage]:
    """GET /stores：分页返回门店；门店账号（store_id 非空）强制只看本店。"""
    result = service.list_stores(
        db,
        page=pagination.page,
        page_size=pagination.page_size,
        keyword=keyword,
        status=status_filter,
        store_id=user.get("store_id"),
    )
    data = StorePage(
        list=[StoreOut.model_validate(item) for item in result.items],
        total=result.total,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return ok(data)


@router.post("", response_model=ApiResponse[StoreOut], summary="新建门店")
def create_store(
    payload: StoreCreate,
    db: DbSession,
    user: CurrentUser,
    service: MasterService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.STORE_WRITE))],
    idempotency_key: IdempotencyKey = None,
) -> ApiResponse[StoreOut]:
    """POST /stores：新建门店；重复提交同一 store_no 返回首次结果。"""
    store = service.create_store(
        db, payload, operator_id=user.get("user_id"), idempotency_key=idempotency_key
    )
    return ok(StoreOut.model_validate(store))


@router.put("/{store_id}", response_model=ApiResponse[StoreOut], summary="修改门店")
def update_store(
    store_id: Annotated[int, Path(ge=1)],
    payload: StoreUpdate,
    db: DbSession,
    user: CurrentUser,
    service: MasterService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.STORE_WRITE))],
) -> ApiResponse[StoreOut]:
    """PUT /stores/{id}：改配送节奏等；version 令牌不一致返回 40900。"""
    store = service.update_store(db, store_id, payload, operator_id=user.get("user_id"))
    return ok(StoreOut.model_validate(store))
