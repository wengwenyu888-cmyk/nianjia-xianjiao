"""对账与核算数据契约（§7.5 reconcile 模型 + §8.2 对账核算组端点）。

约定：
- 请求体用 XxxCreate/XxxConfirm，响应体一律用 XxxOut（api 层禁止直接返回 ORM 对象）；
- 分页响应固定 {list,total,page,page_size}（§8.1）；
- 周期 period 支持 YYYY-Www（ISO 周）/ YYYY-MM（自然月）/ YYYY（自然年），
  与 reconcile.period 的「如 2026-W42」写法一致；
- 金额一律 Decimal，出参保留 2 位（app.utils.unit.money）；
- 收入（门店流水）来自银豹 POS 对接，当前数据模型内没有该表：revenue 缺省 0，
  由调用方显式传入时以传入值为准，revenue_source 标明来源，避免把 0 当成真实流水。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 与 §7.5 的 ENUM 一一对应
ReconcileStatus = Literal["draft", "confirmed", "done"]
# 收入来源：external=调用方传入（银豹流水等）；unavailable=当前无数据源，按 0 计
RevenueSource = Literal["external", "unavailable"]


class ReconcileGenerate(BaseModel):
    """POST /reconciles/generate 请求体（按周期生成对账单）。"""

    period: str = Field(
        min_length=4, max_length=16, description="对账周期，如 2026-W42 / 2026-10 / 2026"
    )
    store_ids: list[int] | None = Field(
        default=None,
        min_length=1,
        description="指定门店；缺省=该周期内有签收数据的全部门店",
    )


class ReconcileConfirm(BaseModel):
    """POST /reconciles/{id}/confirm 请求体（确认并记录与管家婆的差异）。"""

    diff_amount: Decimal = Field(
        default=Decimal("0"), max_digits=14, decimal_places=2, description="与外部台账差异额(元)"
    )
    status: ReconcileStatus = Field(default="confirmed", description="确认状态:confirmed/done")


class ReconcileOut(BaseModel):
    """对账单响应体。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    period: str
    store_id: int
    total_amount: Decimal
    diff_amount: Decimal
    status: str
    confirmed_by: int | None = None
    confirmed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


ReconcileOutList = list[ReconcileOut]


class ReconcilePage(BaseModel):
    """对账单分页响应：data={list,total,page,page_size}。"""

    list: ReconcileOutList = Field(default_factory=list, description="当前页数据")
    total: int = Field(default=0, ge=0, description="总条数")
    page: int = Field(default=1, ge=1, description="当前页码")
    page_size: int = Field(default=20, ge=1, description="每页条数")


class ReconcileGenerateOut(BaseModel):
    """生成结果：generated=本次新建，reused=命中 uk_store_period 复用的既有行。"""

    period: str
    list: ReconcileOutList = Field(default_factory=list, description="本周期各门店对账单")
    generated: int = Field(default=0, ge=0, description="本次新建条数")
    reused: int = Field(default=0, ge=0, description="幂等复用的既有条数")


class StoreProfitOut(BaseModel):
    """门店盈亏响应体（GET /stores/{id}/profit?period=）。

    delivery_cost = 该周期按当时价（内部调拨价优先，缺失退采购价）计算的配货成本，
    与对账单 total_amount 同源；人工/房租/摊销等不在本数据模型内，未计入。
    """

    store_id: int
    store_no: str
    store_name: str
    period: str
    period_start: date
    period_end: date = Field(description="周期末日（含）")
    revenue: Decimal = Field(description="门店收入(元)；无外部数据源时为 0")
    revenue_source: RevenueSource = Field(description="external=调用方传入；unavailable=按 0 计")
    delivery_cost: Decimal = Field(description="配货成本(元)")
    gross_profit: Decimal = Field(description="收入-配货成本(元)")
    gross_margin: Decimal | None = Field(
        default=None, description="毛利率=利润/收入，收入为 0 时为空"
    )
    loss_qty_base: Decimal = Field(default=Decimal("0"), description="周期内已审批报损量(基础单位)")
    sign_qty_base: Decimal = Field(default=Decimal("0"), description="周期内签收实收量(基础单位)")
    reconcile_total_amount: Decimal | None = Field(
        default=None, description="已生成对账单的内部结算额，未生成时为空"
    )
    reconcile_status: str | None = Field(default=None, description="对账单状态，未生成时为空")


class StoreKpiOut(BaseModel):
    """门店 KPI 响应体（GET /stores/{id}/kpi?period=）。

    口径（docs/01 业务手册 + §7 表注释）：
    - 损耗率 = 已审批报损量 ÷ 签收入库量（业务手册：「损耗量 ÷ 入库量」）；
    - 要货准确率 = 1 - Σ|要货量-实收量| ÷ Σ要货量（按 SKU 汇总后逐 SKU 比较）；
    - 配送准确率 = 1 - Σ|应送-实收| ÷ Σ应送（签收差异率，作为要货准确率的对照口径）；
    - 周转天数 = 周期平均库存 ÷ 日均出库量；期初库存 = 期末结存 - 周期内流水净变动，
      出库量 = 周期内 batch_flow 负向变动之和（流水台账口径）。
    """

    store_id: int
    store_no: str
    store_name: str
    period: str
    period_start: date
    period_end: date
    gross_in_qty_base: Decimal = Field(description="签收入库量(基础单位)")
    loss_qty_base: Decimal = Field(description="已审批报损量(基础单位)")
    loss_rate: Decimal | None = Field(default=None, description="损耗率，无入库量时为空")
    order_qty_base: Decimal = Field(description="周期内要货量(基础单位)")
    order_accuracy: Decimal | None = Field(default=None, description="要货准确率，无要货量时为空")
    send_qty_base: Decimal = Field(description="周期内应送量(基础单位)")
    delivery_accuracy: Decimal | None = Field(
        default=None, description="配送准确率，无应送量时为空"
    )
    stock_qty_base: Decimal = Field(description="期末门店结存(基础单位)")
    opening_stock_qty_base: Decimal = Field(description="期初结存=期末-周期内净变动")
    avg_stock_qty_base: Decimal = Field(description="平均库存=(期初+期末)/2")
    outbound_qty_base: Decimal = Field(description="周期内出库量(基础单位)")
    turnover_days: Decimal | None = Field(default=None, description="周转天数，无出库量时为空")
