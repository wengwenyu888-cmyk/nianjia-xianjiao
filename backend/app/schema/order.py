"""要货数据契约（§8.2「要货」组 + §7.3 order_head / order_item）。

约定：
- 请求体 OrderCreate / OrderUpdate，响应体一律 OrderOut（api 层禁止直接返回 ORM 对象）；
- 分页响应固定 {list, total, page, page_size}（§8.1）；
- 明细双列并存：qty_unit（订货单位数量）+ qty_base（基础单位数量）；门店按订货单位下单，
  qty_base 缺省由 service 按 SKU.convert_factor 换算，避免同一事实两处口径；
- order_head 带 version 列（§7.3）：修改/确认/取消回传 version 做乐观锁，不一致 40900。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# 与 §7.3 order_head 的 ENUM 一一对应
OrderStatusValue = Literal["draft", "confirmed", "merged", "cancelled"]
OrderSourceValue = Literal["manual", "agent"]

# 单张要货单明细行上限：防超长请求体拖垮汇总/分拣环节
MAX_ORDER_ITEMS = 200


def _ensure_unique_sku(items: list[OrderItemIn]) -> None:
    """同一 SKU 在一张要货单内只允许一行（汇总按 SKU 聚合，重复行会掩盖口径错误）。"""
    seen: set[int] = set()
    for item in items:
        if item.sku_id in seen:
            raise ValueError(f"同一 SKU 在一张要货单内只能出现一行：sku_id={item.sku_id}")
        seen.add(item.sku_id)


class OrderItemIn(BaseModel):
    """要货明细行请求体：按订货单位下单，qty_base 缺省由 SKU 换算因子推导。"""

    sku_id: int = Field(gt=0, description="逻辑外键→sku.id")
    qty_unit: Decimal = Field(
        gt=0, max_digits=14, decimal_places=3, description="订货单位数量，如 2 袋"
    )
    unit: str | None = Field(
        default=None, min_length=1, max_length=16, description="订货单位；缺省取 SKU.unit"
    )
    qty_base: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=14,
        decimal_places=3,
        description="基础单位数量；缺省= qty_unit × SKU.convert_factor",
    )


class OrderCreate(BaseModel):
    """POST /orders 请求体：门店提交要货单 draft。"""

    store_id: int | None = Field(
        default=None, gt=0, description="门店 id；门店账号可省略（取本人 store_id）"
    )
    require_date: date = Field(description="需求配送日 YYYY-MM-DD")
    items: list[OrderItemIn] = Field(
        min_length=1, max_length=MAX_ORDER_ITEMS, description="要货明细，至少一行"
    )

    @model_validator(mode="after")
    def _check_unique_sku(self) -> Self:
        _ensure_unique_sku(self.items)
        return self


class OrderUpdate(BaseModel):
    """PUT /orders/{id} 请求体：仅草稿可改；items 传入即整单覆盖。"""

    require_date: date | None = Field(default=None, description="需求配送日，可改")
    items: list[OrderItemIn] | None = Field(
        default=None, min_length=1, max_length=MAX_ORDER_ITEMS, description="传入即整单覆盖草稿明细"
    )
    version: int | None = Field(
        default=None, ge=0, description="乐观锁版本令牌，来自查询结果的 version"
    )

    @model_validator(mode="after")
    def _check_unique_sku(self) -> Self:
        if self.items is not None:
            _ensure_unique_sku(self.items)
        return self


class OrderItemOut(BaseModel):
    """要货明细响应体（batch_no 为总部分拣后回填）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    sku_id: int
    qty_base: Decimal
    qty_unit: Decimal
    unit: str
    batch_no: str | None = Field(default=None, description="总部分拣后回填的批次号")


class OrderOut(BaseModel):
    """要货单响应体：头 + 明细（items 由 service 装配，非 ORM 映射列）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    store_id: int
    require_date: date
    status: OrderStatusValue
    source: OrderSourceValue
    agent_suggestion_id: int | None = Field(default=None, description="采纳的智能体建议 id")
    confirm_by: int | None = Field(default=None, description="店长确认人")
    confirm_at: datetime | None = None
    version: int | None = Field(default=None, description="乐观锁版本令牌")
    created_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    items: list[OrderItemOut] = Field(default_factory=list, description="要货明细")

    @model_validator(mode="before")
    @classmethod
    def _project_items(cls, data: Any) -> Any:
        """ORM 实体 → 字段字典：把 service 装配的明细投影进来（dict 入参原样透传）。"""
        if isinstance(data, dict):
            return data
        payload = {name: getattr(data, name, None) for name in cls.model_fields}
        raw_items = getattr(data, "items", None) or ()
        payload["items"] = [OrderItemOut.model_validate(row) for row in raw_items]
        return payload


# 注解别名：字段名就叫 list，会遮蔽内建 list，故先求值成别名（同 schema/store.py）
OrderOutList = list[OrderOut]


class OrderPage(BaseModel):
    """要货单分页响应：data={list,total,page,page_size}（§8.1）。"""

    list: OrderOutList = Field(default_factory=list, description="当前页数据")
    total: int = Field(default=0, ge=0, description="总条数")
    page: int = Field(default=1, ge=1, description="当前页码")
    page_size: int = Field(default=20, ge=1, description="每页条数")
