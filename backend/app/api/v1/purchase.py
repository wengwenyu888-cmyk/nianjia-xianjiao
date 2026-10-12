"""采购接口（§8.2「采购」组，路径与方法与文档逐字一致）。

端点                              默认角色         权限点
POST /purchase-orders             admin, ops       purchase:create
GET  /purchase-orders             admin, ops       purchase:read
POST /purchase-orders/{id}/receive  ops            purchase:receive

挂载方式（由 router.py 统一注册，本文件不自带前缀）：
    api_router.include_router(purchase.router, prefix="/purchase-orders", tags=["采购"])

幂等（§8.1）：写接口支持请求头 Idempotency-Key（≤64 字符）——建单落
purchase_order.idempotency_key（uk_idem 唯一索引兜底），收货用于同键重放。

权限点（§8.3）：purchase:create / purchase:read / purchase:receive 统一取自 core/deps.py 的
PermissionCode（本模块不再本地声明枚举），判定仍走 require_permission。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Path, Query

from app.core.deps import CurrentUser, DbSession, Pagination, PermissionCode, require_permission
from app.schema.common import ApiResponse, ok
from app.schema.purchase import (
    PurchaseCreate,
    PurchaseOrderOut,
    PurchaseOrderPage,
    PurchaseStatusValue,
    ReceiveIn,
)

router = APIRouter()

# 幂等请求头（§8.1，≤64 字符）：同键同体返回首次结果，同键异体 40900
IdempotencyKey = Annotated[
    str | None, Header(alias="Idempotency-Key", max_length=64, description="幂等键，≤64 字符")
]


def get_purchase_service() -> Any:
    """采购服务提供者：api 经依赖注入取 service，测试可整体替换为 fake。"""
    from app.service import purchase_service

    return purchase_service


PurchaseService = Annotated[Any, Depends(get_purchase_service)]


@router.post("", response_model=ApiResponse[PurchaseOrderOut], summary="创建采购单(幂等)")
def create_purchase_order(
    payload: PurchaseCreate,
    db: DbSession,
    user: CurrentUser,
    service: PurchaseService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.PURCHASE_CREATE))],
    idempotency_key: IdempotencyKey = None,
) -> ApiResponse[PurchaseOrderOut]:
    """POST /purchase-orders：落采购单(draft)+明细，单价缺省取 price 表 purchase 当时价。"""
    order = service.create_purchase_order(
        db,
        payload,
        operator_id=user.get("user_id"),
        idempotency_key=idempotency_key,
    )
    return ok(PurchaseOrderOut.model_validate(order))


@router.get("", response_model=ApiResponse[PurchaseOrderPage], summary="采购单列表")
def list_purchase_orders(
    db: DbSession,
    pagination: Pagination,
    user: CurrentUser,
    service: PurchaseService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.PURCHASE_READ))],
    status_filter: Annotated[
        PurchaseStatusValue | None,
        Query(alias="status", description="draft/submitted/received/cancelled"),
    ] = None,
    supplier_id: Annotated[int | None, Query(gt=0, description="供应商 id")] = None,
) -> ApiResponse[PurchaseOrderPage]:
    """GET /purchase-orders?status=&supplier_id=：采购单分页列表（含明细与金额合计）。"""
    result = service.list_purchase_orders(
        db,
        page=pagination.page,
        page_size=pagination.page_size,
        status=status_filter,
        supplier_id=supplier_id,
    )
    data = PurchaseOrderPage(
        list=[PurchaseOrderOut.model_validate(item) for item in result.items],
        total=result.total,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return ok(data)


@router.post(
    "/{po_id}/receive",
    response_model=ApiResponse[PurchaseOrderOut],
    summary="收货→生成批次库存+写 batch_flow 流水(事务)",
)
def receive_purchase_order(
    po_id: Annotated[int, Path(gt=0, description="采购单 id")],
    db: DbSession,
    user: CurrentUser,
    service: PurchaseService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.PURCHASE_RECEIVE))],
    payload: ReceiveIn | None = None,
    idempotency_key: IdempotencyKey = None,
) -> ApiResponse[PurchaseOrderOut]:
    """POST /purchase-orders/{id}/receive：同一事务写批次结存 + receive_add 流水，draft→received。

    body 可省略：等价「按采购单明细未收数量整单收货」，此时必须用头级 expire_at 指定保质期。
    """
    order = service.receive_purchase_order(
        db,
        po_id,
        payload,
        operator_id=user.get("user_id"),
        idempotency_key=idempotency_key,
    )
    return ok(PurchaseOrderOut.model_validate(order))
