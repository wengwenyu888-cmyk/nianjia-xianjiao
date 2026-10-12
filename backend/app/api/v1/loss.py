"""报损接口（§8.2「报损」组，路径与方法与文档逐字一致）。

端点                        用途           默认角色（=权限点集合）
POST /losses                门店提交报损   store_manager(限本店)   loss:create
GET  /losses?store_id=&status=  查报损     admin, ops              loss:read
POST /losses/{id}/approve   总部审批       admin, ops              stock:adjust

挂载方式（由 router.py 统一注册）：
    api_router.include_router(loss.router, prefix="/losses", tags=["报损"])
审批接口天然幂等（draft→approved 只推进一步），不接收 Idempotency-Key：
loss.idempotency_key 的语义是「提交请求幂等键」，由 POST /losses 占用。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Path, Query

from app.api.v1.delivery import actor_from_user
from app.core.deps import CurrentUser, DbSession, Pagination, PermissionCode, require_permission
from app.schema.common import ApiResponse, ok
from app.schema.loss import LossCreate, LossOut, LossPage

router = APIRouter()

IdempotencyKey = Annotated[
    str | None, Header(alias="Idempotency-Key", max_length=64, description="幂等键，≤64 字符")
]


def get_loss_service() -> Any:
    """报损服务提供者：api 经依赖注入取 service，测试可整体替换为 fake。"""
    from app.service import loss_service

    return loss_service


LossService = Annotated[Any, Depends(get_loss_service)]


@router.post("", response_model=ApiResponse[LossOut], summary="门店提交报损")
def create_loss(
    payload: LossCreate,
    db: DbSession,
    user: CurrentUser,
    service: LossService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.LOSS_CREATE))],
    idempotency_key: IdempotencyKey = None,
) -> ApiResponse[LossOut]:
    """POST /losses：落 draft 报损单（不动库存）；门店账号强制本店，重复提交返回首次结果。"""
    loss = service.create_loss(
        db,
        payload,
        actor=actor_from_user(user),
        operator_id=user.get("user_id"),
        idempotency_key=idempotency_key,
    )
    return ok(LossOut.model_validate(loss))


@router.get("", response_model=ApiResponse[LossPage], summary="查报损")
def list_losses(
    db: DbSession,
    pagination: Pagination,
    user: CurrentUser,
    service: LossService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.LOSS_READ))],
    store_id: Annotated[int | None, Query(gt=0, description="门店id")] = None,
    status_filter: Annotated[
        Literal["draft", "approved"] | None, Query(alias="status", description="报损状态")
    ] = None,
) -> ApiResponse[LossPage]:
    """GET /losses?store_id=&status=：报损分页列表（门店账号强制只看本店）。"""
    result = service.list_losses(
        db,
        store_id=service.resolve_list_store_scope(actor_from_user(user), store_id),
        status=status_filter,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    data = LossPage(
        list=[LossOut.model_validate(item) for item in result.items],
        total=result.total,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return ok(data)


@router.post("/{loss_id}/approve", response_model=ApiResponse[LossOut], summary="总部审批报损")
def approve_loss(
    loss_id: Annotated[int, Path(ge=1)],
    db: DbSession,
    user: CurrentUser,
    service: LossService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.STOCK_ADJUST))],
) -> ApiResponse[LossOut]:
    """POST /losses/{id}/approve：draft→approved，同事务扣减 batch_stock + 写 batch_flow。"""
    loss = service.approve_loss(db, loss_id, operator_id=user.get("user_id"))
    return ok(LossOut.model_validate(loss))
