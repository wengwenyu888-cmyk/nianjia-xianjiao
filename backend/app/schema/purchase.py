"""采购数据契约（§8.2「采购」组 + §7.2 purchase_order / purchase_order_item）。

约定：
- 请求体 PurchaseCreate / ReceiveIn，响应体 PurchaseOrderOut（api 层禁止直接返回 ORM 对象）；
- 分页响应固定 {list, total, page, page_size}（§8.1）；
- 精度按 §7 通用约定：单价 DECIMAL(12,4)、数量 DECIMAL(14,3)、金额 DECIMAL(14,2)，
  金额一律用 Decimal 计算，派生字段统一四舍五入到「分」；
- status 值域与 §7.2 purchase_order.status 一一对应，流转只在 service 层发生；
- 契约字段名与落库列名的差异只在本层响应投影里处理：price→unit_price、expect_at→expected_date。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# 与 §7.2 purchase_order.status 一一对应：draft/submitted→received（收货）或 cancelled
PurchaseStatusValue = Literal["draft", "submitted", "received", "cancelled"]

# 金额口径 DECIMAL(14,2)：amount / total_amount 的最小单位「分」
AMOUNT_EXP = Decimal("0.01")


def _amount_of(qty_unit: Any, unit_price: Any) -> Decimal:
    """金额 = 展示单位数量 × 单价（元/展示单位），四舍五入到分。"""
    return (Decimal(qty_unit or 0) * Decimal(unit_price or 0)).quantize(
        AMOUNT_EXP, rounding=ROUND_HALF_UP
    )


# --------------------------------------------------------------------------- 请求体
class PurchaseItemIn(BaseModel):
    """采购明细行：只报展示单位数量，基础单位数量由 service 按 SKU.convert_factor 换算。"""

    sku_id: int = Field(gt=0, description="逻辑外键→sku.id")
    qty_unit: Decimal = Field(gt=0, max_digits=14, decimal_places=3, description="展示单位数量")
    unit: str | None = Field(
        default=None, min_length=1, max_length=16, description="展示单位，缺省取 SKU.unit"
    )
    unit_price: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=4,
        description="下单单价(元/展示单位)，缺省取 price 表 purchase 现行价",
    )


class PurchaseCreate(BaseModel):
    """POST /purchase-orders 请求体（§8.2，幂等走请求头 Idempotency-Key）。"""

    supplier_id: int = Field(gt=0, description="逻辑外键→supplier.id")
    expected_date: date | None = Field(
        default=None, description="预计到货日 YYYY-MM-DD，落库为 purchase_order.expect_at 00:00:00"
    )
    remark: str | None = Field(
        default=None,
        max_length=255,
        description=(
            "备注。当前 purchase_order 表（§7.2 DDL）无 remark 列，传非空值返回 40000；"
            "字段先占位以保证将来加列时线上契约不变"
        ),
    )
    items: list[PurchaseItemIn] = Field(
        min_length=1, description="采购明细：至少 1 行，同一单内 SKU 不允许重复"
    )

    @model_validator(mode="after")
    def _check_items(self) -> Self:
        """明细至少 1 行 + SKU 不重复（重复行会让收货批次生成与金额合计产生歧义）。"""
        sku_ids = [int(item.sku_id) for item in self.items]
        if len(set(sku_ids)) != len(sku_ids):
            raise ValueError("同一采购单内 SKU 不允许重复")
        return self


class ReceiveItemIn(BaseModel):
    """收货明细行：sku_id 必须是本采购单明细中的 SKU；有效期按行→头顺序回退。"""

    sku_id: int = Field(gt=0, description="逻辑外键→sku.id，必须在本采购单明细内")
    qty_base: Decimal = Field(
        gt=0, max_digits=14, decimal_places=3, description="本次收货数量（基础单位）"
    )
    expire_at: datetime | None = Field(
        default=None, description="保质期至，缺省取 ReceiveIn.expire_at；批次必须有保质期"
    )
    unit_price: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=4,
        description="本次到货单价(元/展示单位)，缺省沿用采购单单价",
    )


class ReceiveIn(BaseModel):
    """POST /purchase-orders/{id}/receive 请求体；整个 body 可省略（等价全量收货 + 头级有效期）。"""

    batch_no_prefix: str | None = Field(
        default=None,
        min_length=1,
        max_length=30,
        description="批次号前缀，缺省用采购单号；批次号 = 前缀 + 两位序号",
    )
    expire_at: datetime | None = Field(
        default=None, description="统一保质期至；items 缺省（整单全量收货）时必填"
    )
    items: list[ReceiveItemIn] | None = Field(
        default=None, description="本次收货明细；缺省 = 按采购单明细的未收数量全量收货"
    )


# --------------------------------------------------------------------------- 响应体
class PurchaseItemOut(BaseModel):
    """采购明细响应体：unit_price 对应落库列 price，amount 由 qty_unit×unit_price 派生。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    sku_id: int
    sku_no: str | None = Field(default=None, description="SKU 编码（service 装配）")
    sku_name: str | None = Field(default=None, description="品名（service 装配）")
    qty_unit: Decimal = Field(description="展示单位数量")
    unit: str = Field(description="展示单位")
    qty_base: Decimal = Field(description="基础单位数量 = qty_unit × SKU.convert_factor")
    received_qty_base: Decimal = Field(
        default=Decimal("0.000"), description="已收数量（基础单位），分批收货进度依据"
    )
    unit_price: Decimal = Field(description="下单单价(元/展示单位)，源列名 price")
    amount: Decimal = Field(description="金额(元) = qty_unit × unit_price")

    @model_validator(mode="before")
    @classmethod
    def _project_amount(cls, data: Any) -> Any:
        """ORM 投影：price→unit_price 并派生 amount；dict 入参缺 amount 时同样补算。"""
        if isinstance(data, dict):
            payload = dict(data)
            if payload.get("unit_price") is None:
                payload["unit_price"] = payload.get("price")
            if payload.get("amount") is None:
                payload["amount"] = _amount_of(payload.get("qty_unit"), payload.get("unit_price"))
            return payload
        raw_price = getattr(data, "price", None)
        if raw_price is None:
            raw_price = getattr(data, "unit_price", None)
        qty_unit = getattr(data, "qty_unit", None)
        return {
            "id": getattr(data, "id", None),
            "sku_id": getattr(data, "sku_id", None),
            "sku_no": getattr(data, "sku_no", None),
            "sku_name": getattr(data, "sku_name", None),
            "qty_unit": qty_unit,
            "unit": getattr(data, "unit", None),
            "qty_base": getattr(data, "qty_base", None),
            "received_qty_base": getattr(data, "received_qty_base", None) or Decimal("0.000"),
            "unit_price": raw_price,
            "amount": _amount_of(qty_unit, raw_price),
        }


class PurchaseOrderOut(BaseModel):
    """采购单响应体：头 + 明细（items / supplier_name 由 service 一次查询装配，避免 N+1）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    po_no: str
    supplier_id: int
    supplier_name: str | None = Field(default=None, description="供应商名称（service 装配）")
    status: PurchaseStatusValue
    expected_date: date | None = Field(default=None, description="预计到货日（源列名 expect_at）")
    remark: str | None = Field(
        default=None, description="备注（当前 purchase_order 表无 remark 列，恒为 null）"
    )
    total_amount: Decimal = Field(default=Decimal("0.00"), description="采购金额合计(元)")
    items: list[PurchaseItemOut] = Field(default_factory=list, description="采购明细")

    @model_validator(mode="before")
    @classmethod
    def _project_order(cls, data: Any) -> Any:
        """ORM 投影：expect_at→expected_date、明细装配、金额合计。"""
        if isinstance(data, dict):
            return data
        rows = [PurchaseItemOut.model_validate(row) for row in (getattr(data, "items", None) or ())]
        expect_at = getattr(data, "expect_at", None)
        return {
            "id": getattr(data, "id", None),
            "po_no": getattr(data, "po_no", None),
            "supplier_id": getattr(data, "supplier_id", None),
            "supplier_name": getattr(data, "supplier_name", None),
            "status": getattr(data, "status", None),
            "expected_date": expect_at.date() if isinstance(expect_at, datetime) else expect_at,
            "remark": getattr(data, "remark", None),
            "total_amount": sum((row.amount for row in rows), Decimal("0.00")),
            "items": rows,
        }


# --------------------------------------------------------------------------- 分页响应
# 说明：字段名 list 与 §8.1 契约一致；注解用模块级别名，避免类命名空间里的 list 字段遮蔽内建 list。
PurchaseOrderOutList = list[PurchaseOrderOut]


class PurchaseOrderPage(BaseModel):
    """采购单分页响应：data={list,total,page,page_size}。"""

    list: PurchaseOrderOutList = Field(default_factory=list, description="当前页数据")
    total: int = Field(default=0, ge=0, description="总条数")
    page: int = Field(default=1, ge=1, description="当前页码")
    page_size: int = Field(default=20, ge=1, description="每页条数")
