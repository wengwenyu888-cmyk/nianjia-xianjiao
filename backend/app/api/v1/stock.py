"""库存接口（§8.2「库存」组，路径与方法与文档逐字一致）。

端点                                                          默认角色       权限点
GET  /stocks?store_id=&sku_id=&batch_no=&expire_within_hours=  admin, ops    stock:read
GET  /stocks/alerts?store_id=&expire_hours=&low_qty_base=      admin, ops    stock:read
GET  /stock-flows?store_id=&sku_id=&batch_no=&flow_type=       admin, ops    stock:read

挂载方式（由 router.py 统一注册）：本文件内路由写的是 §8.2 **全路径**
（/stocks、/stocks/alerts、/stock-flows），注册方必须用 router.py 的
_include_optional("stock", prefix="/stocks", probe="/stocks", ...)（probe 命中即不再叠加
prefix）；若改用 include_router(stock.router, prefix="/stocks") 会得到 /stocks/stocks，
路径与文档不一致。

只读：三个端点均为 GET，不接收 Idempotency-Key（§8.1 幂等只覆盖写单据头表），
不写 batch_stock / batch_flow，也不加行锁。

权限点：deps.PermissionCode 目前只含主数据权限点，本模块以本地 StrEnum 声明 §8.3 的
stock:read（取值与 seed/seed.py 的权限点一致）；判定仍走 require_permission（权限点并集）。
数据范围：stock:read 只授予 admin / ops（见 §8.3），无门店账号，故查询不注入本店条件。
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentUser, DbSession, Pagination, require_permission
from app.schema.common import ApiResponse, ok
from app.schema.stock import (
    StockAlertsOut,
    StockFlowOut,
    StockFlowPage,
    StockFlowTypeValue,
    StockOut,
    StockPage,
)
from app.service.stock_service import (
    DEFAULT_ALERT_EXPIRE_HOURS,
    DEFAULT_ALERT_LIMIT,
    DEFAULT_LOW_QTY_BASE,
    MAX_ALERT_LIMIT,
)

router = APIRouter()


class StockPermission(StrEnum):
    """库存模块权限点（§8.3），取值即 permission.code。"""

    READ = "stock:read"


def get_stock_service() -> Any:
    """库存服务提供者：api 经依赖注入取 service，测试可整体替换为 fake。"""
    from app.service import stock_service

    return stock_service


StockService = Annotated[Any, Depends(get_stock_service)]


@router.get(
    "/stocks",
    response_model=ApiResponse[StockPage],
    summary="批次库存查询(支持临期筛选)",
)
def list_stocks(
    db: DbSession,
    pagination: Pagination,
    user: CurrentUser,
    service: StockService,
    _: Annotated[dict[str, Any], Depends(require_permission(StockPermission.READ))],
    store_id: Annotated[
        int | None, Query(ge=0, description="0=总部仓，其余=门店ID；缺省=全部门店与总部仓")
    ] = None,
    sku_id: Annotated[int | None, Query(gt=0, description="SKU id")] = None,
    batch_no: Annotated[str | None, Query(max_length=32, description="批次号（精确匹配）")] = None,
    expire_within_hours: Annotated[
        int | None,
        Query(ge=1, le=8760, description="只看该窗口内到期批次(含已过期)，并作 expiring 阈值"),
    ] = None,
    include_zero: Annotated[
        bool, Query(description="true=含零/负结存批次；缺省 false 只返回有货批次")
    ] = False,
) -> ApiResponse[StockPage]:
    """GET /stocks：门店×SKU×批次结存分页；hours_to_expire / expiring 按当前时间算。"""
    result = service.list_stocks(
        db,
        store_id=store_id,
        sku_id=sku_id,
        batch_no=batch_no,
        expire_within_hours=expire_within_hours,
        include_zero=include_zero,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    data = StockPage(
        list=[StockOut.model_validate(item) for item in result.items],
        total=result.total,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return ok(data)


@router.get(
    "/stocks/alerts",
    response_model=ApiResponse[StockAlertsOut],
    summary="临期与低库存预警汇总",
)
def stock_alerts(
    db: DbSession,
    user: CurrentUser,
    service: StockService,
    _: Annotated[dict[str, Any], Depends(require_permission(StockPermission.READ))],
    store_id: Annotated[
        int | None, Query(ge=0, description="0=总部仓；缺省=总部仓（与低库存口径一致）")
    ] = None,
    expire_hours: Annotated[
        int, Query(ge=1, le=8760, description="临期窗口（小时），缺省 24")
    ] = DEFAULT_ALERT_EXPIRE_HOURS,
    low_qty_base: Annotated[
        Decimal, Query(ge=0, description="低库存阈值（基础单位），缺省 20")
    ] = DEFAULT_LOW_QTY_BASE,
    limit: Annotated[
        int, Query(ge=1, le=MAX_ALERT_LIMIT, description="每条清单最多返回条数")
    ] = DEFAULT_ALERT_LIMIT,
) -> ApiResponse[StockAlertsOut]:
    """GET /stocks/alerts：临期批次清单 + 低库存 SKU 清单（无分页，受 limit 约束）。"""
    alerts = service.stock_alerts(
        db,
        store_id=store_id,
        expire_hours=expire_hours,
        low_qty_base=low_qty_base,
        limit=limit,
    )
    return ok(StockAlertsOut.model_validate(alerts))


@router.get(
    "/stock-flows",
    response_model=ApiResponse[StockFlowPage],
    summary="批次流水查询(收/发/报损/盘点)",
)
def list_stock_flows(
    db: DbSession,
    pagination: Pagination,
    user: CurrentUser,
    service: StockService,
    _: Annotated[dict[str, Any], Depends(require_permission(StockPermission.READ))],
    store_id: Annotated[
        int | None, Query(ge=0, description="0=总部仓，其余=门店ID；缺省=全部")
    ] = None,
    sku_id: Annotated[int | None, Query(gt=0, description="SKU id")] = None,
    batch_no: Annotated[str | None, Query(max_length=32, description="批次号（精确匹配）")] = None,
    flow_type: Annotated[
        StockFlowTypeValue | None,
        Query(description="receive_add/pick_sub/loss_sub/count_adjust"),
    ] = None,
) -> ApiResponse[StockFlowPage]:
    """GET /stock-flows：按 occurred_at desc, id desc 分页，可回溯谁在何时因哪张单改动。"""
    result = service.list_stock_flows(
        db,
        store_id=store_id,
        sku_id=sku_id,
        batch_no=batch_no,
        flow_type=flow_type,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    data = StockFlowPage(
        list=[StockFlowOut.model_validate(item) for item in result.items],
        total=result.total,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return ok(data)
