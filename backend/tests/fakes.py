"""接口层测试替身（SQLite 内存库与 MySQL 方言类型不兼容，故不连库）。

本地跑法（backend 目录下）：
    uv run pytest
    # 或（本机 python 已装 fastapi/pydantic/pytest 时）：
    python -m pytest tests/ -q

- fake service：接口层只断言路由装配、参数传递与统一响应结构；
- row_* 构造器：造出带 updated_at 的 ORM 风格对象，供 XxxOut.model_validate 使用；
- install_overrides：一次性替换 get_db / get_current_user 与全部模块的 get_*_service
  提供者（未传 fake 的模块不注册覆盖，避免误伤其它测试）；
- 数据范围（§8.1）与状态机（40900）的判定在真实 service 层，故 fake 里同样复刻一份
  「门店账号越权 → PermissionDeniedError(40300) / 非法流转 → ConflictError(40900)」，
  这样接口层能验证统一的错误响应体与 HTTP 映射。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Annotated, Any

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api.v1.agent import get_agent_service
from app.api.v1.delivery import get_delivery_service
from app.api.v1.loss import get_loss_service
from app.api.v1.orders import get_order_service
from app.api.v1.picking import get_summary_service as get_pick_service
from app.api.v1.purchase import get_purchase_service
from app.api.v1.receipt import get_receipt_service
from app.api.v1.settlement import get_settlement_service
from app.api.v1.stock import get_stock_service
from app.api.v1.summary import get_summary_service
from app.core.deps import (
    bearer_scheme,
    get_auth_service,
    get_current_user,
    get_db,
    get_master_service,
)
from app.core.exceptions import (
    BusinessError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.main import app
from app.schema.stock import StockAlertItem, StockAlertsOut, StockAlertSummary, StockOut
from app.service.store_service import PageResult

_NOW = datetime(2026, 10, 12, 10, 0, 0)
_EXPIRE_AT = datetime(2026, 10, 20, 12, 0, 0)


# ======================================================================= 主数据行
def store_row(**overrides: Any) -> SimpleNamespace:
    """门店 ORM 风格对象。"""
    base: dict[str, Any] = {
        "id": 1,
        "store_no": "S001",
        "name": "示例门店",
        "region": "上海",
        "address": "某路 1 号",
        "contact_name": "店长",
        "contact_phone": "13800000000",
        "delivery_cycle": "daily",
        "status": 1,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def sku_row(**overrides: Any) -> SimpleNamespace:
    """SKU ORM 风格对象。"""
    base: dict[str, Any] = {
        "id": 1,
        "sku_no": "K001",
        "name": "猪肉馅",
        "category": "馅料-肉馅",
        "spec": "5kg/袋",
        "unit": "袋",
        "base_unit": "kg",
        "convert_factor": Decimal("5.0000"),
        "shelf_life_hours": 72,
        "supply_type": "direct",
        "status": 1,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def supplier_row(**overrides: Any) -> SimpleNamespace:
    """供应商 ORM 风格对象。"""
    base: dict[str, Any] = {
        "id": 1,
        "supplier_no": "G001",
        "name": "某食品厂",
        "contact_name": "业务员",
        "contact_phone": "13900000000",
        "payment_terms": 30,
        "status": 1,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def price_row(**overrides: Any) -> SimpleNamespace:
    """价目 ORM 风格对象。"""
    base: dict[str, Any] = {
        "id": 1,
        "sku_id": 100,
        "price_type": "purchase",
        "price": Decimal("3.5000"),
        "effective_from": date(2026, 1, 1),
        "effective_to": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ======================================================================= 业务单据行
def order_item_row(**overrides: Any) -> SimpleNamespace:
    """要货明细行（OrderItemOut 投影）。"""
    base: dict[str, Any] = {
        "id": 11,
        "order_id": 1,
        "sku_id": 100,
        "qty_base": Decimal("10.000"),
        "qty_unit": Decimal("2.000"),
        "unit": "袋",
        "batch_no": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def order_row(**overrides: Any) -> SimpleNamespace:
    """要货单头（OrderOut 投影，items 为 service 装配的瞬时属性）。"""
    base: dict[str, Any] = {
        "id": 1,
        "order_no": "DD202610120001",
        "store_id": 3,
        "require_date": date(2026, 10, 13),
        "status": "draft",
        "source": "manual",
        "agent_suggestion_id": None,
        "confirm_by": None,
        "confirm_at": None,
        "version": 0,
        "created_by": 7,
        "created_at": _NOW,
        "updated_at": _NOW,
        "items": [order_item_row()],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def summary_item_row(**overrides: Any) -> SimpleNamespace:
    """汇总明细行（SummaryItemOut 投影）。"""
    base: dict[str, Any] = {
        "id": 21,
        "summary_id": 1,
        "sku_id": 100,
        "total_qty_base": Decimal("30.000"),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def summary_row(**overrides: Any) -> SimpleNamespace:
    """汇总单头（SummaryOut 投影）。"""
    base: dict[str, Any] = {
        "id": 1,
        "summary_no": "HZ202610130001",
        "require_date": date(2026, 10, 13),
        "status": "generated",
        "line_count": 1,
        "idempotency_key": None,
        "created_by": 7,
        "created_at": _NOW,
        "updated_at": _NOW,
        "items": [summary_item_row()],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def pick_item_row(**overrides: Any) -> SimpleNamespace:
    """分拣明细行（PickItemOut 投影，批次在此落定）。"""
    base: dict[str, Any] = {
        "id": 31,
        "pick_id": 1,
        "sku_id": 100,
        "batch_no": "B20261001",
        "qty_base": Decimal("10.000"),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def pick_row(**overrides: Any) -> SimpleNamespace:
    """分拣单头（PickOut 投影）。"""
    base: dict[str, Any] = {
        "id": 1,
        "pick_no": "FJ202610130001",
        "summary_id": 1,
        "store_id": 3,
        "status": "created",
        "version": 0,
        "idempotency_key": None,
        "created_by": 7,
        "created_at": _NOW,
        "updated_at": _NOW,
        "items": [pick_item_row()],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def suggestion_row(**overrides: Any) -> SimpleNamespace:
    """智能体建议快照（SuggestionOut 投影）。"""
    base: dict[str, Any] = {
        "id": 1,
        "suggestion_type": "order_suggest",
        "store_id": 3,
        "require_date": date(2026, 10, 13),
        "payload": {
            "policy": "rule-v1",
            "items": [
                {
                    "sku_id": 100,
                    "sku_no": "K001",
                    "suggest_qty_base": "10.000",
                    "suggest_qty_unit": "2.000",
                    "unit": "袋",
                }
            ],
            "warnings": [],
        },
        "apply_status": "pending",
        "applied_by": None,
        "applied_at": None,
        "order_id": None,
        "model": "rule-v1",
        "version": 0,
        "created_by": 7,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def pick_plan_payload(**overrides: Any) -> dict[str, Any]:
    """pick_plan 建议快照 payload（落 agent_suggestion.payload，形状即 PickPlanOut）。"""
    payload: dict[str, Any] = {
        "policy": "rule-v1",
        "generated_at": _NOW,
        "require_date": date(2026, 10, 13),
        "tasks": [
            {
                "store_id": 3,
                "sku_id": 100,
                "required_qty_base": Decimal("10.000"),
                "allocated_qty_base": Decimal("8.000"),
                "shortage_qty_base": Decimal("2.000"),
                "batches": [
                    {
                        "batch_no": "B20261001",
                        "qty_base": Decimal("8.000"),
                        "expire_at": _EXPIRE_AT,
                        "produced_at": date(2026, 10, 1),
                    }
                ],
                "flags": ["总部仓预演缺口 2.000，需补货或拆分配送"],
            }
        ],
        "warnings": ["门店 3 的 SKU 100 预演缺口 2.000"],
        "total_required_qty_base": Decimal("10.000"),
        "total_shortage_qty_base": Decimal("2.000"),
    }
    payload.update(overrides)
    return payload


def delivery_item_row(**overrides: Any) -> SimpleNamespace:
    """配送明细行（DeliveryItemOut 投影）。"""
    base: dict[str, Any] = {
        "id": 41,
        "pick_item_id": 31,
        "sku_id": 100,
        "batch_no": "B20261001",
        "qty_base": Decimal("10.000"),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def delivery_row(**overrides: Any) -> SimpleNamespace:
    """配送单头（DeliveryOut.build 逐字段取属性，故必须是 ORM 风格对象）。"""
    base: dict[str, Any] = {
        "id": 1,
        "delivery_no": "PS202610130001",
        "summary_id": 1,
        "store_id": 3,
        "require_date": date(2026, 10, 13),
        "driver_id": 9,
        "plate_no": "沪A12345",
        "status": "loaded",
        "loaded_at": _NOW,
        "signed_at": None,
        "created_at": _NOW,
        "updated_at": _NOW,
        "items": [delivery_item_row()],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def sign_item_row(**overrides: Any) -> SimpleNamespace:
    """签收明细行（SignItemOut 投影，diff_qty_base 为数据库生成列）。"""
    base: dict[str, Any] = {
        "id": 51,
        "sku_id": 100,
        "batch_no": "B20261001",
        "send_qty_base": Decimal("10.000"),
        "sign_qty_base": Decimal("8.000"),
        "diff_qty_base": Decimal("2.000"),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def sign_row(**overrides: Any) -> SimpleNamespace:
    """签收单头（SignOut.build 取属性）。"""
    base: dict[str, Any] = {
        "id": 1,
        "delivery_id": 1,
        "store_id": 3,
        "sign_by": 7,
        "sign_at": _NOW,
        "status": "partial",
        "remark": None,
        "created_at": _NOW,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def loss_row(**overrides: Any) -> SimpleNamespace:
    """报损单（LossOut 投影）。"""
    base: dict[str, Any] = {
        "id": 1,
        "loss_no": "BS202610130001",
        "store_id": 3,
        "sku_id": 100,
        "batch_no": "B20261001",
        "qty_base": Decimal("2.000"),
        "type": "expire",
        "reason": "临期",
        "status": "draft",
        "approved_by": None,
        "approved_at": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def reconcile_row(**overrides: Any) -> SimpleNamespace:
    """对账单（ReconcileOut 投影）。"""
    base: dict[str, Any] = {
        "id": 1,
        "period": "2026-W42",
        "store_id": 3,
        "total_amount": Decimal("1200.00"),
        "diff_amount": Decimal("0.00"),
        "status": "draft",
        "confirmed_by": None,
        "confirmed_at": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class FakePeriodWindow:
    """周期窗口（settlement_service.PeriodWindow 的等价投影，含 last_day 计算属性）。"""

    def __init__(
        self,
        code: str = "2026-W42",
        start: date = date(2026, 10, 12),
        end: date = date(2026, 10, 19),
    ) -> None:
        self.code = code
        self.start = start
        self.end = end

    @property
    def last_day(self) -> date:
        """周期末日（含）：api 层 _profit_out / _kpi_out 会取该属性。"""
        return self.end - timedelta(days=1)


def period_window_row(**overrides: Any) -> FakePeriodWindow:
    """周期窗口替身（默认 2026-W42：10-12 ~ 10-18）。"""
    window = FakePeriodWindow()
    for key, value in overrides.items():
        setattr(window, key, value)
    return window


def store_profit_result(**overrides: Any) -> SimpleNamespace:
    """门店盈亏聚合结果（api 层 _profit_out 逐字段取属性）。"""
    base: dict[str, Any] = {
        "store": store_row(id=3, store_no="S003", name="三号店"),
        "window": period_window_row(),
        "revenue": Decimal("3000.00"),
        "revenue_source": "external",
        "delivery_cost": Decimal("1200.00"),
        "gross_profit": Decimal("1800.00"),
        "gross_margin": Decimal("0.6000"),
        "loss_qty": Decimal("2.000"),
        "sign_qty": Decimal("8.000"),
        "reconcile": reconcile_row(),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def store_kpi_result(**overrides: Any) -> SimpleNamespace:
    """门店 KPI 聚合结果（api 层 _kpi_out 逐字段取属性）。"""
    base: dict[str, Any] = {
        "store": store_row(id=3, store_no="S003", name="三号店"),
        "window": period_window_row(),
        "gross_in_qty": Decimal("8.000"),
        "loss_qty": Decimal("2.000"),
        "loss_rate": Decimal("0.2500"),
        "order_qty": Decimal("10.000"),
        "order_accuracy": Decimal("0.8000"),
        "send_qty": Decimal("10.000"),
        "delivery_accuracy": Decimal("0.8000"),
        "stock_qty": Decimal("6.000"),
        "opening_stock_qty": Decimal("4.000"),
        "avg_stock_qty": Decimal("5.000"),
        "outbound_qty": Decimal("6.000"),
        "turnover_days": Decimal("5.83"),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def purchase_item_row(**overrides: Any) -> SimpleNamespace:
    """采购明细行（PurchaseItemOut 投影：price→unit_price、amount 派生）。"""
    base: dict[str, Any] = {
        "id": 61,
        "po_id": 1,
        "sku_id": 100,
        "sku_no": "K001",
        "sku_name": "猪肉馅",
        "qty_unit": Decimal("2.000"),
        "unit": "袋",
        "qty_base": Decimal("10.000"),
        "received_qty_base": Decimal("0.000"),
        "price": Decimal("3.5000"),
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def purchase_order_row(**overrides: Any) -> SimpleNamespace:
    """采购单头（PurchaseOrderOut 投影：expect_at→expected_date、明细装配）。"""
    base: dict[str, Any] = {
        "id": 1,
        "po_no": "CG202610130001",
        "supplier_id": 5,
        "supplier_name": "某食品厂",
        "status": "draft",
        "expect_at": datetime(2026, 10, 14, 0, 0, 0),
        "remark": None,
        "created_at": _NOW,
        "updated_at": _NOW,
        "items": [purchase_item_row()],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def stock_out_row(**overrides: Any) -> SimpleNamespace:
    """批次库存行（stock_service.list_stocks 已装配成 StockOut，故直接给 schema 字段）。"""
    base: dict[str, Any] = {
        "id": 71,
        "store_id": 0,
        "store_name": "总部仓",
        "sku_id": 100,
        "sku_no": "K001",
        "sku_name": "猪肉馅",
        "batch_no": "B20261001",
        "qty_base": Decimal("10.000"),
        "unit": "袋",
        "convert_factor": Decimal("5.0000"),
        "expire_at": _EXPIRE_AT,
        "hours_to_expire": Decimal("192.00"),
        "expiring": False,
        "created_at": _NOW,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def stock_alert_item(**overrides: Any) -> StockAlertItem:
    """低库存预警行：与真实 service 一致，直接构造 StockAlertItem（无 from_attributes）。"""
    base: dict[str, Any] = {
        "sku_id": 100,
        "sku_no": "K001",
        "sku_name": "猪肉馅",
        "qty_base": Decimal("5.000"),
        "unit": "袋",
        "threshold": Decimal("20.000"),
        "batch_count": 1,
    }
    base.update(overrides)
    return StockAlertItem(**base)


def stock_alerts_result(
    *,
    expiring: list[Any] | None = None,
    low_stock: list[Any] | None = None,
    expiring_count: int = 1,
    low_stock_count: int = 1,
    expire_hours: int = 24,
    low_qty_base: Any = Decimal("20.000"),
    as_of: Any = _NOW,
) -> StockAlertsOut:
    """预警汇总结果：与真实 service 一致，直接构造 StockAlertsOut（无 from_attributes）。"""
    return StockAlertsOut(
        expiring=expiring
        if expiring is not None
        else [
            StockOut.model_validate(stock_out_row(expiring=True, hours_to_expire=Decimal("12.00")))
        ],
        low_stock=low_stock if low_stock is not None else [stock_alert_item()],
        summary=StockAlertSummary(
            expiring_count=expiring_count,
            low_stock_count=low_stock_count,
            expire_hours=expire_hours,
            low_qty_base=Decimal(low_qty_base),
            as_of=as_of,
        ),
    )


def stock_flow_out_row(**overrides: Any) -> SimpleNamespace:
    """批次流水行（stock_service.list_stock_flows 已装配成 StockFlowOut）。"""
    base: dict[str, Any] = {
        "id": 81,
        "store_id": 0,
        "store_name": "总部仓",
        "sku_id": 100,
        "sku_no": "K001",
        "sku_name": "猪肉馅",
        "batch_no": "B20261001",
        "flow_type": "receive_add",
        "qty_change_base": Decimal("10.000"),
        "qty_after_base": Decimal("10.000"),
        "doc_type": "purchase_order",
        "doc_no": "CG202610130001",
        "operate_by": 7,
        "occurred_at": _NOW,
        "remark": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ======================================================================= 主数据
class FakeMasterService:
    """记录调用的假服务：接口层验证路由与参数，不触碰数据库。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.stores: list[Any] = []
        self.skus: list[Any] = []
        self.suppliers: list[Any] = []
        self.prices: list[Any] = []

    # ---- 门店
    def list_stores(self, db: Any, **kwargs: Any) -> PageResult[Any]:
        self.calls.append(("list_stores", kwargs))
        return PageResult(items=self.stores, total=len(self.stores))

    def create_store(self, db: Any, payload: Any, **kwargs: Any) -> Any:
        self.calls.append(("create_store", {"payload": payload, **kwargs}))
        return store_row(id=1, **payload.model_dump())

    def update_store(self, db: Any, store_id: int, payload: Any, **kwargs: Any) -> Any:
        self.calls.append(("update_store", {"store_id": store_id, "payload": payload, **kwargs}))
        return store_row(id=store_id, **payload.model_dump(exclude_unset=True, exclude={"version"}))

    # ---- SKU
    def list_skus(self, db: Any, **kwargs: Any) -> PageResult[Any]:
        self.calls.append(("list_skus", kwargs))
        return PageResult(items=self.skus, total=len(self.skus))

    def create_sku(self, db: Any, payload: Any, **kwargs: Any) -> Any:
        self.calls.append(("create_sku", {"payload": payload, **kwargs}))
        return sku_row(id=1, **payload.model_dump())

    # ---- 供应商
    def list_suppliers(self, db: Any, **kwargs: Any) -> PageResult[Any]:
        self.calls.append(("list_suppliers", kwargs))
        return PageResult(items=self.suppliers, total=len(self.suppliers))

    def create_supplier(self, db: Any, payload: Any, **kwargs: Any) -> Any:
        self.calls.append(("create_supplier", {"payload": payload, **kwargs}))
        return supplier_row(id=1, **payload.model_dump())

    # ---- 价目
    def list_prices(self, db: Any, **kwargs: Any) -> PageResult[Any]:
        self.calls.append(("list_prices", kwargs))
        return PageResult(items=self.prices, total=len(self.prices))

    def create_price(self, db: Any, payload: Any, **kwargs: Any) -> Any:
        self.calls.append(("create_price", {"payload": payload, **kwargs}))
        return price_row(id=1, **payload.model_dump())


# ======================================================================= 要货
class FakeOrderService:
    """要货 service 替身：复刻数据范围（§8.1）与状态机（§8.3）的对外语义。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.order: Any = order_row()
        self.orders: list[Any] = []

    def create_order(self, db: Any, payload: Any, **kwargs: Any) -> Any:
        self.calls.append(("create_order", {"payload": payload, **kwargs}))
        scope = kwargs.get("store_id_scope")
        store_id = int(payload.store_id) if payload.store_id is not None else scope
        if store_id is None:
            raise BusinessError("总部账号创建要货单时必须指定 store_id")
        if scope is not None and store_id != int(scope):
            raise PermissionDeniedError("门店账号只能为本店创建要货单")
        return order_row(store_id=store_id, require_date=payload.require_date)

    def update_order(self, db: Any, order_id: int, payload: Any, **kwargs: Any) -> Any:
        self.calls.append(("update_order", {"order_id": order_id, "payload": payload, **kwargs}))
        row = order_row(id=order_id)
        if payload.require_date is not None:
            row.require_date = payload.require_date
        if payload.items is not None:
            row.items = [
                order_item_row(id=10 + index, order_id=order_id, sku_id=item.sku_id)
                for index, item in enumerate(payload.items, start=1)
            ]
        return row

    def confirm_order(self, db: Any, order_id: int, **kwargs: Any) -> Any:
        self.calls.append(("confirm_order", {"order_id": order_id, **kwargs}))
        return order_row(
            id=order_id,
            status="confirmed",
            confirm_by=kwargs.get("operator_id"),
            confirm_at=_NOW,
            version=1,
        )

    def cancel_order(self, db: Any, order_id: int, **kwargs: Any) -> Any:
        self.calls.append(("cancel_order", {"order_id": order_id, **kwargs}))
        return order_row(id=order_id, status="cancelled", version=1)

    def list_orders(self, db: Any, **kwargs: Any) -> PageResult[Any]:
        self.calls.append(("list_orders", kwargs))
        scope = kwargs.get("store_id_scope")
        store_id = kwargs.get("store_id")
        if scope is not None:
            if store_id is not None and int(store_id) != int(scope):
                raise PermissionDeniedError("门店账号只能查询本店要货单")
            store_id = int(scope)
        rows = list(self.orders)
        if store_id is not None:
            rows = [row for row in rows if int(row.store_id) == int(store_id)]
        require_date = kwargs.get("require_date")
        if require_date is not None:
            rows = [row for row in rows if row.require_date == require_date]
        status = kwargs.get("status")
        if status is not None:
            rows = [row for row in rows if row.status == status]
        return PageResult(items=rows, total=len(rows))


# ======================================================================= 汇总 / 分拣
class FakeSummaryService:
    """汇总分拣 service 替身：summary 与 pick 两组端点共用本 fake（真实亦同一个模块）。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.summary: Any = summary_row()
        self.summaries: list[Any] = []
        self.pick: Any = pick_row()
        self.picks: list[Any] = []
        # create_pick 用：需要模拟「库内已有分拣单」的错误场景时显式设置
        self.pick_error: Exception | None = None
        self.duplicate_pick_error: Exception | None = None

    # ---- 汇总
    def generate_summary(self, db: Any, **kwargs: Any) -> Any:
        self.calls.append(("generate_summary", kwargs))
        return summary_row(require_date=kwargs.get("require_date"))

    def list_summaries(self, db: Any, **kwargs: Any) -> PageResult[Any]:
        self.calls.append(("list_summaries", kwargs))
        rows = list(self.summaries)
        if kwargs.get("require_date") is not None:
            rows = [row for row in rows if row.require_date == kwargs["require_date"]]
        if kwargs.get("status") is not None:
            rows = [row for row in rows if row.status == kwargs["status"]]
        return PageResult(items=rows, total=len(rows))

    # ---- 分拣
    def create_pick(self, db: Any, payload: Any, **kwargs: Any) -> Any:
        self.calls.append(("create_pick", {"payload": payload, **kwargs}))
        if self.pick_error is not None:
            raise self.pick_error
        if self.duplicate_pick_error is not None:
            raise self.duplicate_pick_error
        return pick_row(summary_id=payload.summary_id, store_id=payload.store_id)

    def list_picks(self, db: Any, **kwargs: Any) -> PageResult[Any]:
        self.calls.append(("list_picks", kwargs))
        rows = list(self.picks)
        store_id = kwargs.get("store_id")
        if store_id is not None:
            rows = [row for row in rows if int(row.store_id) == int(store_id)]
        summary_id = kwargs.get("summary_id")
        if summary_id is not None:
            rows = [row for row in rows if int(row.summary_id) == int(summary_id)]
        status = kwargs.get("status")
        if status is not None:
            rows = [row for row in rows if row.status == status]
        return PageResult(items=rows, total=len(rows))

    def complete_pick(self, db: Any, pick_id: int, **kwargs: Any) -> Any:
        self.calls.append(("complete_pick", {"pick_id": pick_id, **kwargs}))
        return pick_row(id=pick_id, status="done", version=1)


# ======================================================================= 智能体
class FakeAgentService:
    """智能体 service 替身：建议快照与只读 FIFO 预演（不落账）。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.suggestion: Any = suggestion_row()
        self.plan: Any = suggestion_row(
            id=2,
            suggestion_type="pick_plan",
            store_id=0,
            payload=pick_plan_payload(),
        )
        self.order: Any = order_row(source="agent", agent_suggestion_id=1)

    def generate_order_suggestions(self, db: Any, payload: Any, **kwargs: Any) -> Any:
        self.calls.append(("generate_order_suggestions", {"payload": payload, **kwargs}))
        scope = kwargs.get("store_id_scope")
        store_id = int(payload.store_id) if payload.store_id is not None else scope
        if store_id is None:
            raise BusinessError("生成要货建议时必须指定 store_id")
        if scope is not None and store_id != int(scope):
            raise PermissionDeniedError("门店账号只能为本店生成要货建议")
        return suggestion_row(
            store_id=store_id,
            require_date=payload.require_date,
            created_by=kwargs.get("operator_id"),
        )

    def get_suggestion(self, db: Any, suggestion_id: int, **kwargs: Any) -> Any:
        self.calls.append(("get_suggestion", {"suggestion_id": suggestion_id, **kwargs}))
        row = self.suggestion
        scope = kwargs.get("store_id_scope")
        if scope is not None and int(row.store_id) != int(scope):
            raise PermissionDeniedError("门店账号只能查看本店建议")
        return row

    def apply_suggestion(self, db: Any, suggestion_id: int, **kwargs: Any) -> Any:
        self.calls.append(("apply_suggestion", {"suggestion_id": suggestion_id, **kwargs}))
        row = self.suggestion
        scope = kwargs.get("store_id_scope")
        if scope is not None and int(row.store_id) != int(scope):
            raise PermissionDeniedError("门店账号只能采纳本店建议")
        if row.apply_status != "pending":
            raise ConflictError(f"建议当前状态为 {row.apply_status}，不能采纳")
        return order_row(
            store_id=row.store_id,
            require_date=row.require_date,
            source="agent",
            agent_suggestion_id=suggestion_id,
        )

    def build_pick_plan(self, db: Any, payload: Any, **kwargs: Any) -> Any:
        self.calls.append(("build_pick_plan", {"payload": payload, **kwargs}))
        return self.plan


# ======================================================================= 配送 / 签收
class FakeDeliveryService:
    """配送签收 service 替身：复刻门店/司机数据范围与状态机语义。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.delivery: Any = delivery_row()
        self.deliveries: list[Any] = []
        self.items: list[Any] = [delivery_item_row()]
        self.sign_row: Any = sign_row()
        self.sign_items: list[Any] = [sign_item_row()]
        # depart / sign 用：需要模拟「未装车就发车」「状态与明细推导不一致」等错误时显式设置
        self.depart_error: Exception | None = None
        self.sign_error: Exception | None = None

    def _view(self, row: Any, actor: Any) -> None:
        """复刻 assert_can_view：门店限本店、纯司机限本人任务。"""
        if actor is None:
            return
        if actor.store_id is not None and int(row.store_id) != int(actor.store_id):
            raise PermissionDeniedError("只能查看本店的配送单")
        if getattr(actor, "is_driver_scoped", False) and row.driver_id != actor.user_id:
            raise PermissionDeniedError("司机只能查看自己的配送任务")

    def create_delivery(self, db: Any, payload: Any, **kwargs: Any) -> Any:
        self.calls.append(("create_delivery", {"payload": payload, **kwargs}))
        actor = kwargs.get("actor")
        if (
            actor is not None
            and actor.store_id is not None
            and int(payload.store_id) != int(actor.store_id)
        ):
            raise PermissionDeniedError("门店账号只能为本店装车")
        return delivery_row(
            store_id=payload.store_id,
            summary_id=payload.summary_id,
            require_date=payload.require_date,
            driver_id=payload.driver_id,
            plate_no=payload.plate_no,
        )

    def list_delivery_items(self, db: Any, delivery_id: int) -> list[Any]:
        self.calls.append(("list_delivery_items", {"delivery_id": delivery_id}))
        return list(self.items)

    def list_deliveries(self, db: Any, **kwargs: Any) -> PageResult[Any]:
        self.calls.append(("list_deliveries", kwargs))
        actor = kwargs.get("actor")
        rows = list(self.deliveries)
        if actor is not None and actor.store_id is not None:
            rows = [row for row in rows if int(row.store_id) == int(actor.store_id)]
        if actor is not None and getattr(actor, "is_driver_scoped", False):
            driver_id = kwargs.get("driver_id")
            if driver_id is not None and int(driver_id) != int(actor.user_id):
                raise PermissionDeniedError("司机只能查看自己的配送任务")
            rows = [row for row in rows if row.driver_id == actor.user_id]
        elif kwargs.get("driver_id") is not None:
            rows = [row for row in rows if row.driver_id == kwargs["driver_id"]]
        if kwargs.get("require_date") is not None:
            rows = [row for row in rows if row.require_date == kwargs["require_date"]]
        if kwargs.get("status") is not None:
            rows = [row for row in rows if row.status == kwargs["status"]]
        return PageResult(items=rows, total=len(rows))

    def get_delivery(self, db: Any, delivery_id: int, **kwargs: Any) -> Any:
        self.calls.append(("get_delivery", {"delivery_id": delivery_id, **kwargs}))
        row = self.delivery
        if int(row.id) != int(delivery_id):
            raise NotFoundError("配送单不存在")
        self._view(row, kwargs.get("actor"))
        return row

    def depart(self, db: Any, delivery_id: int, **kwargs: Any) -> Any:
        self.calls.append(("depart", {"delivery_id": delivery_id, **kwargs}))
        actor = kwargs.get("actor")
        if actor is not None and actor.store_id is not None:
            raise PermissionDeniedError("门店账号不能执行发车操作")
        if self.depart_error is not None:
            raise self.depart_error
        return delivery_row(id=delivery_id, status="on_way")

    def sign(self, db: Any, delivery_id: int, payload: Any, **kwargs: Any) -> Any:
        """签收：数据范围（门店/司机）先判定，其次明细覆盖一致性（缺行/多行 40000）。"""
        self.calls.append(("sign", {"delivery_id": delivery_id, "payload": payload, **kwargs}))
        if self.sign_error is not None:
            raise self.sign_error
        row = self.sign_row
        actor = kwargs.get("actor")
        if (
            actor is not None
            and actor.store_id is not None
            and int(row.store_id) != int(actor.store_id)
        ):
            raise PermissionDeniedError("只能签收本店的配送单")
        if (
            actor is not None
            and getattr(actor, "is_driver_scoped", False)
            and int(self.delivery.driver_id or 0) != int(actor.user_id or 0)
        ):
            raise PermissionDeniedError("司机只能签收自己的配送任务")
        if len(payload.items) != len(self.items):
            raise BusinessError("签收明细与配送明细不一致（缺行/多行）")
        return sign_row(delivery_id=delivery_id)

    def get_sign(self, db: Any, sign_id: int, **kwargs: Any) -> Any:
        self.calls.append(("get_sign", {"sign_id": sign_id, **kwargs}))
        actor = kwargs.get("actor")
        if (
            actor is not None
            and actor.store_id is not None
            and int(self.sign_row.store_id) != int(actor.store_id)
        ):
            raise PermissionDeniedError("只能查看本店的签收单")
        if (
            actor is not None
            and getattr(actor, "is_driver_scoped", False)
            and int(self.delivery.driver_id or 0) != int(actor.user_id or 0)
        ):
            raise PermissionDeniedError("司机只能查看自己配送任务的签收单")
        return SimpleNamespace(
            sign=self.sign_row,
            items=list(self.sign_items),
            delivery=self.delivery,
        )


# ======================================================================= 报损
class FakeLossService:
    """报损 service 替身：门店限本店、审批推进 draft→approved。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.loss: Any = loss_row()
        self.losses: list[Any] = []

    @staticmethod
    def resolve_store_id(payload: Any, actor: Any) -> int:
        """复刻真实 service 的门店归属判定（门店账号强制本店，跨店 40300）。"""
        if actor is not None and actor.store_id is not None:
            if payload.store_id is not None and int(payload.store_id) != int(actor.store_id):
                raise PermissionDeniedError("门店账号只能为本店提交报损")
            return int(actor.store_id)
        if payload.store_id is None:
            raise BusinessError("总部账号提交报损必须指定 store_id")
        return int(payload.store_id)

    @staticmethod
    def resolve_list_store_scope(actor: Any, store_id: int | None) -> int | None:
        """复刻列表数据范围（门店账号显式请求他店 → 40300）。"""
        if actor is None or actor.store_id is None:
            return store_id
        if store_id is not None and int(store_id) != int(actor.store_id):
            raise PermissionDeniedError("门店账号只能查看本店的报损单")
        return int(actor.store_id)

    def create_loss(self, db: Any, payload: Any, **kwargs: Any) -> Any:
        self.calls.append(("create_loss", {"payload": payload, **kwargs}))
        return loss_row(
            store_id=self.resolve_store_id(payload, kwargs.get("actor")),
            sku_id=payload.sku_id,
            batch_no=payload.batch_no,
            qty_base=payload.qty_base,
            type=payload.type,
            reason=payload.reason,
        )

    def list_losses(self, db: Any, **kwargs: Any) -> PageResult[Any]:
        self.calls.append(("list_losses", kwargs))
        rows = list(self.losses)
        if kwargs.get("store_id") is not None:
            rows = [row for row in rows if int(row.store_id) == int(kwargs["store_id"])]
        if kwargs.get("status") is not None:
            rows = [row for row in rows if row.status == kwargs["status"]]
        return PageResult(items=rows, total=len(rows))

    def approve_loss(self, db: Any, loss_id: int, **kwargs: Any) -> Any:
        self.calls.append(("approve_loss", {"loss_id": loss_id, **kwargs}))
        return loss_row(
            id=loss_id,
            status="approved",
            approved_by=kwargs.get("operator_id"),
            approved_at=_NOW,
        )


# ======================================================================= 对账核算
class FakeSettlementService:
    """对账核算 service 替身：列表数据范围 + 盈亏/KPI 装配。"""

    def __init__(
        self,
        *,
        reconciles: list[Any] | None = None,
        profit: Any = None,
        kpi: Any = None,
        store_scope: Any = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.batch: Any = SimpleNamespace(
            period="2026-W42", rows=[reconcile_row()], generated=1, reused=0
        )
        self.reconciles: list[Any] = list(reconciles or [])
        self.profit: Any = profit or store_profit_result()
        self.kpi: Any = kpi or store_kpi_result()
        # store_scope=({"允许的 store_id 集合"}, ValueError 文案) 风格的越权开关
        self.store_scope: Any = store_scope

    def _assert_scope(self, store_id: int) -> None:
        if self.store_scope is None:
            return
        allowed, message = self.store_scope
        if int(store_id) not in {int(item) for item in allowed}:
            raise PermissionDeniedError(message)

    def resolve_store_scope(self, actor: Any, store_id: int | None) -> int | None:
        """复刻列表数据范围（门店账号强制本店，显式请求他店 → 40300）。"""
        if actor is None or actor.store_id is None:
            return store_id
        if store_id is not None and int(store_id) != int(actor.store_id):
            raise PermissionDeniedError("只能查看本店的核算数据")
        return int(actor.store_id)

    def generate_reconcile(self, db: Any, **kwargs: Any) -> Any:
        self.calls.append(("generate_reconcile", kwargs))
        actor = kwargs.get("actor")
        for store_id in kwargs.get("store_ids") or ():
            if (
                actor is not None
                and actor.store_id is not None
                and int(store_id) != int(actor.store_id)
            ):
                raise PermissionDeniedError("只能查看本店的核算数据")
            self._assert_scope(int(store_id))
        return self.batch

    def list_reconciles(self, db: Any, **kwargs: Any) -> PageResult[Any]:
        self.calls.append(("list_reconciles", kwargs))
        rows = list(self.reconciles)
        if kwargs.get("period") is not None:
            rows = [row for row in rows if row.period == kwargs["period"]]
        if kwargs.get("store_id") is not None:
            rows = [row for row in rows if int(row.store_id) == int(kwargs["store_id"])]
        return PageResult(items=rows, total=len(rows))

    def confirm_reconcile(self, db: Any, reconcile_id: int, payload: Any, **kwargs: Any) -> Any:
        self.calls.append(
            ("confirm_reconcile", {"reconcile_id": reconcile_id, "payload": payload, **kwargs})
        )
        return reconcile_row(
            id=reconcile_id,
            status=payload.status,
            diff_amount=payload.diff_amount,
            confirmed_by=kwargs.get("operator_id"),
            confirmed_at=_NOW,
        )

    def store_profit(self, db: Any, store_id: int, period: str, **kwargs: Any) -> Any:
        self.calls.append(("store_profit", {"store_id": store_id, "period": period, **kwargs}))
        if (
            kwargs.get("actor") is not None
            and kwargs["actor"].store_id is not None
            and int(store_id) != int(kwargs["actor"].store_id)
        ):
            raise PermissionDeniedError("只能查看本店的核算数据")
        self._assert_scope(store_id)
        return self.profit

    def store_kpi(self, db: Any, store_id: int, period: str, **kwargs: Any) -> Any:
        self.calls.append(("store_kpi", {"store_id": store_id, "period": period, **kwargs}))
        if (
            kwargs.get("actor") is not None
            and kwargs["actor"].store_id is not None
            and int(store_id) != int(kwargs["actor"].store_id)
        ):
            raise PermissionDeniedError("只能查看本店的核算数据")
        self._assert_scope(store_id)
        return self.kpi


# ======================================================================= 采购
class FakePurchaseService:
    """采购 service 替身：建单/列表/收货（收货状态机 40900 由调用方显式注入）。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.purchase_order: Any = purchase_order_row()
        self.purchase_orders: list[Any] = []
        self.receive_order: Any = purchase_order_row(status="received", items=[])

    def create_purchase_order(self, db: Any, payload: Any, **kwargs: Any) -> Any:
        self.calls.append(("create_purchase_order", {"payload": payload, **kwargs}))
        return purchase_order_row(
            supplier_id=payload.supplier_id,
            expect_at=(
                datetime.combine(payload.expected_date, datetime.min.time())
                if payload.expected_date is not None
                else None
            ),
        )

    def list_purchase_orders(self, db: Any, **kwargs: Any) -> PageResult[Any]:
        self.calls.append(("list_purchase_orders", kwargs))
        rows = list(self.purchase_orders)
        if kwargs.get("status") is not None:
            rows = [row for row in rows if row.status == kwargs["status"]]
        if kwargs.get("supplier_id") is not None:
            rows = [row for row in rows if int(row.supplier_id) == int(kwargs["supplier_id"])]
        return PageResult(items=rows, total=len(rows))

    def receive_purchase_order(
        self, db: Any, po_id: int, payload: Any = None, **kwargs: Any
    ) -> Any:
        self.calls.append(
            ("receive_purchase_order", {"po_id": po_id, "payload": payload, **kwargs})
        )
        return self.receive_order


# ======================================================================= 库存
class FakeStockService:
    """库存 service 替身（只读三端点）：记录筛选参数并返回装配好的响应行。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.stocks: list[Any] = []
        self.flows: list[Any] = []
        self.alerts: Any = stock_alerts_result()

    def list_stocks(self, db: Any, **kwargs: Any) -> PageResult[Any]:
        self.calls.append(("list_stocks", kwargs))
        rows = list(self.stocks)
        if kwargs.get("store_id") is not None:
            rows = [row for row in rows if int(row.store_id) == int(kwargs["store_id"])]
        if kwargs.get("include_zero") is False:
            rows = [row for row in rows if Decimal(row.qty_base) > 0]
        return PageResult(items=rows, total=len(rows))

    def stock_alerts(self, db: Any, **kwargs: Any) -> Any:
        self.calls.append(("stock_alerts", kwargs))
        return self.alerts

    def list_stock_flows(self, db: Any, **kwargs: Any) -> PageResult[Any]:
        self.calls.append(("list_stock_flows", kwargs))
        rows = list(self.flows)
        if kwargs.get("flow_type") is not None:
            rows = [row for row in rows if row.flow_type == kwargs["flow_type"]]
        return PageResult(items=rows, total=len(rows))


# ======================================================================= 依赖覆盖
def install_overrides(
    service: Any = None,
    *,
    permissions: Iterable[Any] = (),
    role: str = "admin",
    store_id: int | None = None,
    extra_roles: Iterable[str] = (),
    store: Any = None,
    sku: Any = None,
    supplier: Any = None,
    price: Any = None,
    order: Any = None,
    summary: Any = None,
    pick: Any = None,
    agent: Any = None,
    delivery: Any = None,
    receipt: Any = None,
    loss: Any = None,
    settlement: Any = None,
    purchase: Any = None,
    stock: Any = None,
) -> None:
    """把 get_db / get_current_user 与各模块 get_*_service 全部替换为测试替身。

    用法（新业务模块）：
        install_overrides(None, permissions={"order:create"}, order=fake_order)

    - service/store/sku/supplier/price 走主数据提供者（兼容既有测试的写法）；
    - 每个业务模块没传 fake 时**不注册覆盖**，避免把该模块的 service 注入成 None；
    - role / store_id / extra_roles 决定 40300 数据范围用例：门店账号需 store_id 非空，
      纯司机用 role="driver" 且 store_id=None。
    """
    overrides: dict[Any, Any] = {
        get_db: lambda: None,
        get_current_user: lambda: _current_user(
            permissions=permissions, role=role, store_id=store_id, extra_roles=extra_roles
        ),
    }

    master = service or store or sku or supplier or price
    if master is not None:
        overrides[get_master_service] = lambda: master
    modules: dict[Any, Any] = {
        get_order_service: order,
        get_summary_service: summary,
        get_pick_service: pick,
        get_agent_service: agent,
        get_delivery_service: delivery,
        get_receipt_service: receipt,
        get_loss_service: loss,
        get_settlement_service: settlement,
        get_purchase_service: purchase,
        get_stock_service: stock,
    }
    for provider, fake in modules.items():
        if fake is not None:
            overrides[provider] = _constant(fake)

    app.dependency_overrides.update(overrides)


def _constant(value: Any) -> Any:
    """把 fake 包成 FastAPI 依赖：必须每次返回同一对象，测试才能读它的 calls。"""
    return lambda: value


def _current_user(
    *,
    permissions: Iterable[Any],
    role: str,
    store_id: int | None,
    extra_roles: Iterable[str] = (),
) -> dict[str, Any]:
    """当前用户替身：permissions 决定 40300；store_id 决定数据范围。"""
    roles = list(dict.fromkeys([role, *extra_roles]))
    return {
        "user_id": 7,
        "username": "tester",
        "name": "测试用户",
        "role": role,
        "roles": roles,
        "store_id": store_id,
        "permissions": [str(code) for code in permissions],
    }


class FakeAuthService:
    """假认证服务：不连库、不依赖 jose / passlib，只验证 api 层的 40100 分支。

    passwords：口令正确的用户；deleted_users：模拟已软删/停用的用户（口令对也拒绝）。
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.passwords: dict[str, str] = {"zhangsan": "St0re#2026"}
        self.deleted_users: set[str] = {"lisi"}
        self.token = "fake-jwt-token"
        self.profile: dict[str, Any] = {
            "id": 7,
            "username": "zhangsan",
            "display_name": "张三",
            "store_id": 3,
            "role_codes": ["store_manager"],
            "permission_codes": ["master:store:read", "order:create"],
        }

    def authenticate(self, db: Any, username: str, password: str) -> dict[str, Any] | None:
        """镜像真实服务语义：不存在 / 软删 / 口令错误一律 None。"""
        self.calls.append((username, password))
        if username in self.deleted_users:
            return None
        expected = self.passwords.get(username)
        if expected is None or password != expected:
            return None
        return {"token": self.token, "token_type": "bearer", "user": dict(self.profile)}


def install_auth_overrides(
    auth_service: Any,
    *,
    profile: dict[str, Any] | None = None,
) -> None:
    """认证接口测试替身：替换 auth service，并让 get_current_user 真实校验 Bearer。

    与 install_overrides 的差别：这里不直接返回固定用户，而是先检查 Authorization 头，
    这样「/auth/me 必须带 Bearer」才有可断言的 40100（不解析 JWT，故无需 jose）。
    """
    current = profile or {
        "user_id": 7,
        "username": "zhangsan",
        "name": "张三",
        "role": "store",
        "roles": ["store_manager"],
        "store_id": 3,
        "permissions": ["master:store:read"],
    }

    def fake_current_user(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    ) -> dict[str, Any]:
        if credentials is None or not credentials.credentials:
            raise HTTPException(
                status_code=401,
                detail="未登录或缺少访问令牌",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return current

    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_current_user] = fake_current_user
