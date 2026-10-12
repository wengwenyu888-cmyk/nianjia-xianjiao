"""对账核算接口（§8.2「对账核算」组，路径与方法与文档逐字一致）。

端点                                用途                默认角色（=权限点集合）
POST /reconciles/generate           按周期生成对账单     admin                  reconcile:generate
GET  /reconciles?period=&store_id=  查对账               admin, ops             reconcile:read
POST /reconciles/{id}/confirm       确认(记录管家婆差异) admin                  reconcile:confirm
GET  /stores/{id}/profit?period=    门店盈亏核算         admin, ops             report:profit
GET  /stores/{id}/kpi?period=       KPI(损耗/准确率/周转) admin, ops            report:kpi

挂载方式（由 router.py 统一注册；前三条在 /reconciles 前缀，后两条在 /stores 前缀）：
    api_router.include_router(settlement.router, prefix="/reconciles", tags=["对账核算"])
    api_router.include_router(settlement.stores_router, prefix="/stores", tags=["对账核算"])
stores_router 只有 /{id}/profit 与 /{id}/kpi 两个 GET，不与 stores.py 的 /stores、
PUT /stores/{id} 冲突（路径不同段数/方法）。

收入口径：门店流水来自银豹 POS 对接（本数据模型内无该表），/stores/{id}/profit 的
可选 revenue 参数用于接入前手工传入流水，缺省按 0 计并在 revenue_source 标注。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Path, Query

from app.api.v1.delivery import actor_from_user
from app.core.deps import CurrentUser, DbSession, Pagination, PermissionCode, require_permission
from app.schema.common import ApiResponse, ok
from app.schema.settlement import (
    ReconcileConfirm,
    ReconcileGenerate,
    ReconcileGenerateOut,
    ReconcileOut,
    ReconcilePage,
    StoreKpiOut,
    StoreProfitOut,
)

# 对账端点（/reconciles）
router = APIRouter()
# 门店核算端点（/stores）
stores_router = APIRouter()

IdempotencyKey = Annotated[
    str | None, Header(alias="Idempotency-Key", max_length=64, description="幂等键，≤64 字符")
]


def get_settlement_service() -> Any:
    """对账核算服务提供者：api 经依赖注入取 service，测试可整体替换为 fake。"""
    from app.service import settlement_service

    return settlement_service


SettlementService = Annotated[Any, Depends(get_settlement_service)]


def _profit_out(result: Any) -> StoreProfitOut:
    """装配门店盈亏响应体（api 层只做协议转换）。"""
    reconcile = result.reconcile
    return StoreProfitOut(
        store_id=result.store.id,
        store_no=result.store.store_no,
        store_name=result.store.name,
        period=result.window.code,
        period_start=result.window.start,
        period_end=result.window.last_day,
        revenue=result.revenue,
        revenue_source=result.revenue_source,
        delivery_cost=result.delivery_cost,
        gross_profit=result.gross_profit,
        gross_margin=result.gross_margin,
        loss_qty_base=result.loss_qty,
        sign_qty_base=result.sign_qty,
        reconcile_total_amount=reconcile.total_amount if reconcile is not None else None,
        reconcile_status=reconcile.status if reconcile is not None else None,
    )


def _kpi_out(result: Any) -> StoreKpiOut:
    """装配门店 KPI 响应体。"""
    return StoreKpiOut(
        store_id=result.store.id,
        store_no=result.store.store_no,
        store_name=result.store.name,
        period=result.window.code,
        period_start=result.window.start,
        period_end=result.window.last_day,
        gross_in_qty_base=result.gross_in_qty,
        loss_qty_base=result.loss_qty,
        loss_rate=result.loss_rate,
        order_qty_base=result.order_qty,
        order_accuracy=result.order_accuracy,
        send_qty_base=result.send_qty,
        delivery_accuracy=result.delivery_accuracy,
        stock_qty_base=result.stock_qty,
        opening_stock_qty_base=result.opening_stock_qty,
        avg_stock_qty_base=result.avg_stock_qty,
        outbound_qty_base=result.outbound_qty,
        turnover_days=result.turnover_days,
    )


@router.post(
    "/generate", response_model=ApiResponse[ReconcileGenerateOut], summary="按周期生成对账单"
)
def generate_reconcile(
    payload: ReconcileGenerate,
    db: DbSession,
    user: CurrentUser,
    service: SettlementService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.RECONCILE_GENERATE))],
    idempotency_key: IdempotencyKey = None,
) -> ApiResponse[ReconcileGenerateOut]:
    """POST /reconciles/generate：按周期聚合配送签收数据逐店生成对账单（uk_store_period 幂等）。"""
    batch = service.generate_reconcile(
        db,
        period=payload.period,
        store_ids=payload.store_ids,
        actor=actor_from_user(user),
        operator_id=user.get("user_id"),
        idempotency_key=idempotency_key,
    )
    data = ReconcileGenerateOut(
        period=batch.period,
        list=[ReconcileOut.model_validate(row) for row in batch.rows],
        generated=batch.generated,
        reused=batch.reused,
    )
    return ok(data)


@router.get("", response_model=ApiResponse[ReconcilePage], summary="查对账")
def list_reconciles(
    db: DbSession,
    pagination: Pagination,
    user: CurrentUser,
    service: SettlementService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.RECONCILE_READ))],
    period: Annotated[
        str | None, Query(min_length=4, max_length=16, description="如 2026-W42")
    ] = None,
    store_id: Annotated[int | None, Query(gt=0, description="门店id")] = None,
) -> ApiResponse[ReconcilePage]:
    """GET /reconciles?period=&store_id=：对账分页列表（门店账号强制只看本店）。"""
    result = service.list_reconciles(
        db,
        period=period,
        store_id=service.resolve_store_scope(actor_from_user(user), store_id),
        page=pagination.page,
        page_size=pagination.page_size,
    )
    data = ReconcilePage(
        list=[ReconcileOut.model_validate(item) for item in result.items],
        total=result.total,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return ok(data)


@router.post(
    "/{reconcile_id}/confirm", response_model=ApiResponse[ReconcileOut], summary="确认对账"
)
def confirm_reconcile(
    reconcile_id: Annotated[int, Path(ge=1)],
    payload: ReconcileConfirm,
    db: DbSession,
    user: CurrentUser,
    service: SettlementService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.RECONCILE_CONFIRM))],
    idempotency_key: IdempotencyKey = None,
) -> ApiResponse[ReconcileOut]:
    """POST /reconciles/{id}/confirm：记录与管家婆差异额并推进 draft→confirmed→done。"""
    row = service.confirm_reconcile(
        db,
        reconcile_id,
        payload,
        operator_id=user.get("user_id"),
        idempotency_key=idempotency_key,
    )
    return ok(ReconcileOut.model_validate(row))


@stores_router.get(
    "/{store_id}/profit", response_model=ApiResponse[StoreProfitOut], summary="门店盈亏核算"
)
def get_store_profit(
    store_id: Annotated[int, Path(ge=1)],
    db: DbSession,
    user: CurrentUser,
    service: SettlementService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.REPORT_PROFIT))],
    period: Annotated[str, Query(min_length=4, max_length=16, description="如 2026-W42")],
    revenue: Annotated[
        Decimal | None,
        Query(ge=0, max_digits=14, decimal_places=2, description="门店收入(元)，缺省=无数据源按 0"),
    ] = None,
) -> ApiResponse[StoreProfitOut]:
    """GET /stores/{id}/profit?period=：收入-配货成本=利润；成本与对账单 total_amount 同口径。"""
    result = service.store_profit(
        db, store_id, period, revenue=revenue, actor=actor_from_user(user)
    )
    return ok(_profit_out(result))


@stores_router.get("/{store_id}/kpi", response_model=ApiResponse[StoreKpiOut], summary="门店KPI")
def get_store_kpi(
    store_id: Annotated[int, Path(ge=1)],
    db: DbSession,
    user: CurrentUser,
    service: SettlementService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.REPORT_KPI))],
    period: Annotated[str, Query(min_length=4, max_length=16, description="如 2026-W42")],
) -> ApiResponse[StoreKpiOut]:
    """GET /stores/{id}/kpi?period=：损耗率/要货准确率/配送准确率/周转天数（SQL 聚合）。"""
    result = service.store_kpi(db, store_id, period, actor=actor_from_user(user))
    return ok(_kpi_out(result))
