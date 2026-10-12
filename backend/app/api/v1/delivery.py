"""配送单接口（§8.2「配送签收」组，路径与方法与文档逐字一致）。

端点                          默认角色                权限点
POST /deliveries              ops                     delivery:create
GET  /deliveries               driver, ops            delivery:read
GET  /deliveries/{id}          driver, ops            delivery:read
POST /deliveries/{id}/depart   driver                 delivery:depart
POST /deliveries/{id}/sign     store_manager, driver  sign:create

挂载方式（由 router.py 统一注册，本文件不自带前缀）：
    api_router.include_router(delivery.router, prefix="/deliveries", tags=["配送签收"])
签收单详情 GET /signs/{id} 在 receipt.py（同一条业务链，单独前缀 /signs）。

权限点（§8.3）：delivery:create / delivery:read / delivery:depart / sign:create 统一取自
core/deps.py 的 PermissionCode（本模块不再本地声明枚举），判定仍走 require_permission。
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Path, Query

from app.core.deps import CurrentUser, DbSession, Pagination, PermissionCode, require_permission
from app.schema.common import ApiResponse, ok
from app.schema.delivery import (
    DeliveryCreate,
    DeliveryOut,
    DeliveryPage,
    SignIn,
    SignOut,
)
from app.service.delivery_service import Actor

router = APIRouter()

# 幂等请求头（§8.1，≤64 字符）：同键同体返回首次结果，同键异体 40900
IdempotencyKey = Annotated[
    str | None, Header(alias="Idempotency-Key", max_length=64, description="幂等键，≤64 字符")
]


def actor_from_user(user: dict[str, Any]) -> Actor:
    """由 CurrentUser 装配调用者身份（数据范围判定用）。

    供配送/签收/报损/对账各 api 模块共用，避免同一份「user→Actor」映射多处实现。
    """
    return Actor(
        user_id=user.get("user_id"),
        store_id=user.get("store_id"),
        roles=frozenset(user.get("roles") or ()),
    )


def get_delivery_service() -> Any:
    """配送服务提供者：api 经依赖注入取 service，测试可整体替换为 fake。"""
    from app.service import delivery_service

    return delivery_service


DeliveryService = Annotated[Any, Depends(get_delivery_service)]


@router.post("", response_model=ApiResponse[DeliveryOut], summary="生成配送单(装车)")
def create_delivery(
    payload: DeliveryCreate,
    db: DbSession,
    user: CurrentUser,
    service: DeliveryService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.DELIVERY_CREATE))],
    idempotency_key: IdempotencyKey = None,
) -> ApiResponse[DeliveryOut]:
    """POST /deliveries：落配送单(loaded)+明细；items 缺省按分拣明细派生，重复提交返回首次结果。"""
    delivery = service.create_delivery(
        db,
        payload,
        actor=actor_from_user(user),
        operator_id=user.get("user_id"),
        idempotency_key=idempotency_key,
    )
    items = service.list_delivery_items(db, delivery.id)
    return ok(DeliveryOut.build(delivery, items=items))


@router.get("", response_model=ApiResponse[DeliveryPage], summary="司机当日任务/配送单列表")
def list_deliveries(
    db: DbSession,
    pagination: Pagination,
    user: CurrentUser,
    service: DeliveryService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.DELIVERY_READ))],
    driver_id: Annotated[int | None, Query(gt=0, description="司机id；纯司机按本人过滤")] = None,
    require_date: Annotated[date | None, Query(description="配送日 YYYY-MM-DD")] = None,
    status_filter: Annotated[
        Literal["loaded", "on_way", "signed", "partial", "rejected"] | None,
        Query(alias="status", description="配送状态筛选"),
    ] = None,
) -> ApiResponse[DeliveryPage]:
    """GET /deliveries?driver_id=&require_date=：司机当日任务；门店账号强制只看本店。"""
    result = service.list_deliveries(
        db,
        actor=actor_from_user(user),
        driver_id=driver_id,
        require_date=require_date,
        status=status_filter,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    data = DeliveryPage(
        list=[DeliveryOut.build(item) for item in result.items],
        total=result.total,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return ok(data)


@router.get("/{delivery_id}", response_model=ApiResponse[DeliveryOut], summary="配送单详情")
def get_delivery(
    delivery_id: Annotated[int, Path(ge=1)],
    db: DbSession,
    user: CurrentUser,
    service: DeliveryService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.DELIVERY_READ))],
) -> ApiResponse[DeliveryOut]:
    """GET /deliveries/{id}：带全量明细；司机只能看自己的任务，门店账号只能看本店。"""
    delivery = service.get_delivery(db, delivery_id, actor=actor_from_user(user))
    items = service.list_delivery_items(db, delivery.id)
    return ok(DeliveryOut.build(delivery, items=items))


@router.post("/{delivery_id}/depart", response_model=ApiResponse[DeliveryOut], summary="发车")
def depart_delivery(
    delivery_id: Annotated[int, Path(ge=1)],
    db: DbSession,
    user: CurrentUser,
    service: DeliveryService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.DELIVERY_DEPART))],
) -> ApiResponse[DeliveryOut]:
    """POST /deliveries/{id}/depart：loaded → on_way；非法流转 40900。"""
    delivery = service.depart(
        db, delivery_id, actor=actor_from_user(user), operator_id=user.get("user_id")
    )
    return ok(DeliveryOut.build(delivery))


@router.post("/{delivery_id}/sign", response_model=ApiResponse[SignOut], summary="签收(电子POD)")
def sign_delivery(
    delivery_id: Annotated[int, Path(ge=1)],
    payload: SignIn,
    db: DbSession,
    user: CurrentUser,
    service: DeliveryService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.SIGN_CREATE))],
    idempotency_key: IdempotencyKey = None,
) -> ApiResponse[SignOut]:
    """POST /deliveries/{id}/sign：写 sign+sign_item（差异由生成列计算）并落定门店库存。

    实收明细须覆盖该配送单全部明细；重复提交同键同体返回首次结果，异体 40900。
    """
    sign = service.sign(
        db,
        delivery_id,
        payload,
        actor=actor_from_user(user),
        operator_id=user.get("user_id"),
        idempotency_key=idempotency_key,
    )
    detail = service.get_sign(db, sign.id, actor=actor_from_user(user))
    return ok(
        SignOut.build(detail.sign, items=detail.items, delivery_no=detail.delivery.delivery_no)
    )
