"""要货接口（§8.2「要货」组）。

端点：
- POST /orders                        门店提交要货单 draft（幂等）
- PUT  /orders/{id}                   修改草稿明细
- POST /orders/{id}/confirm           店长确认生效（draft→confirmed）
- POST /orders/{id}/cancel            取消（仅 confirmed 前）
- GET  /orders?store_id=&require_date=&status=   查询要货单

权限点（§8.3）：order:create / order:update / order:confirm / order:cancel / order:read。
说明：这批权限点在 core/deps.py 的 PermissionCode 里尚未登记（该文件先落地了主数据模块），
故此处用等值 StrEnum 声明，取值与 §8.3 逐字一致，后续并入 PermissionCode 可无缝替换。
数据范围（§8.1）：门店账号（user.store_id 非空）只能操作/查询本店数据，越权 40300。
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Path, Query

from app.core.deps import CurrentUser, DbSession, Pagination, require_permission
from app.schema.common import ApiResponse, ok
from app.schema.order import OrderCreate, OrderOut, OrderPage, OrderStatusValue, OrderUpdate

router = APIRouter()


class OrderPermission(StrEnum):
    """要货模块权限点（§8.3），取值即 permission.code。"""

    CREATE = "order:create"
    UPDATE = "order:update"
    CONFIRM = "order:confirm"
    CANCEL = "order:cancel"
    READ = "order:read"


def get_order_service() -> Any:
    """要货服务提供者：api 经依赖注入取 service，测试可整体替换为 fake。"""
    from app.service import order_service

    return order_service


OrderService = Annotated[Any, Depends(get_order_service)]

# 幂等请求头（§8.1，≤64 字符）：写接口统一支持，重复提交返回首次结果
IdempotencyKey = Annotated[
    str | None, Header(alias="Idempotency-Key", max_length=64, description="幂等键，≤64 字符")
]


@router.post("", response_model=ApiResponse[OrderOut], summary="门店提交要货单(draft)")
def create_order(
    payload: OrderCreate,
    db: DbSession,
    user: CurrentUser,
    service: OrderService,
    _: Annotated[dict[str, Any], Depends(require_permission(OrderPermission.CREATE))],
    idempotency_key: IdempotencyKey = None,
) -> ApiResponse[OrderOut]:
    """POST /orders：建 draft 要货单；门店账号只能为本店建单，重复提交返回首次结果。"""
    order = service.create_order(
        db,
        payload,
        store_id_scope=user.get("store_id"),
        operator_id=user.get("user_id"),
        idempotency_key=idempotency_key,
    )
    return ok(OrderOut.model_validate(order))


@router.put("/{order_id}", response_model=ApiResponse[OrderOut], summary="修改草稿明细")
def update_order(
    order_id: Annotated[int, Path(ge=1)],
    payload: OrderUpdate,
    db: DbSession,
    user: CurrentUser,
    service: OrderService,
    _: Annotated[dict[str, Any], Depends(require_permission(OrderPermission.UPDATE))],
    idempotency_key: IdempotencyKey = None,
) -> ApiResponse[OrderOut]:
    """PUT /orders/{id}：仅草稿可改；items 传入即整单覆盖，version 不一致 40900。"""
    order = service.update_order(
        db,
        order_id,
        payload,
        store_id_scope=user.get("store_id"),
        operator_id=user.get("user_id"),
    )
    return ok(OrderOut.model_validate(order))


@router.post("/{order_id}/confirm", response_model=ApiResponse[OrderOut], summary="店长确认生效")
def confirm_order(
    order_id: Annotated[int, Path(ge=1)],
    db: DbSession,
    user: CurrentUser,
    service: OrderService,
    _: Annotated[dict[str, Any], Depends(require_permission(OrderPermission.CONFIRM))],
    idempotency_key: IdempotencyKey = None,
) -> ApiResponse[OrderOut]:
    """POST /orders/{id}/confirm：draft→confirmed，落 confirm_by/confirm_at。"""
    order = service.confirm_order(
        db, order_id, store_id_scope=user.get("store_id"), operator_id=user.get("user_id")
    )
    return ok(OrderOut.model_validate(order))


@router.post("/{order_id}/cancel", response_model=ApiResponse[OrderOut], summary="取消要货单")
def cancel_order(
    order_id: Annotated[int, Path(ge=1)],
    db: DbSession,
    user: CurrentUser,
    service: OrderService,
    _: Annotated[dict[str, Any], Depends(require_permission(OrderPermission.CANCEL))],
    idempotency_key: IdempotencyKey = None,
) -> ApiResponse[OrderOut]:
    """POST /orders/{id}/cancel：仅 confirmed 前可取消，确认后 40900。"""
    order = service.cancel_order(
        db, order_id, store_id_scope=user.get("store_id"), operator_id=user.get("user_id")
    )
    return ok(OrderOut.model_validate(order))


@router.get("", response_model=ApiResponse[OrderPage], summary="查询要货单")
def list_orders(
    db: DbSession,
    pagination: Pagination,
    user: CurrentUser,
    service: OrderService,
    _: Annotated[dict[str, Any], Depends(require_permission(OrderPermission.READ))],
    store_id: Annotated[int | None, Query(gt=0, description="门店 id，门店账号只能传本店")] = None,
    require_date: Annotated[date | None, Query(description="需求配送日 YYYY-MM-DD")] = None,
    status_filter: Annotated[
        OrderStatusValue | None,
        Query(alias="status", description="draft/confirmed/merged/cancelled"),
    ] = None,
) -> ApiResponse[OrderPage]:
    """GET /orders：分页查询；门店账号强制只看本店（越权传他店 40300）。"""
    result = service.list_orders(
        db,
        page=pagination.page,
        page_size=pagination.page_size,
        store_id=store_id,
        require_date=require_date,
        status=status_filter,
        store_id_scope=user.get("store_id"),
    )
    data = OrderPage(
        list=[OrderOut.model_validate(item) for item in result.items],
        total=result.total,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return ok(data)
