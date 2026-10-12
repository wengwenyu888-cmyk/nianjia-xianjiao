"""库存数据契约（§8.2「库存」组三条只读端点 + §7.2 batch_stock / batch_flow）。

约定：
- 只读契约：本模块只定义响应体，不含任何写请求体——库存变动由收货（purchase）/
  分拣（summary）/ 签收（delivery）/ 报损审批（loss）各模块在事务内写结存 + 流水；
- 分页响应固定 {list, total, page, page_size}（§8.1）；
- flow_type / doc_type 值域与 §7.2 DDL 的 ENUM 逐字一致，避免前端拿到未定义取值；
- 时间口径：expire_at / occurred_at / as_of 一律为「无时区本地时间」（与 DDL DATETIME、
  服务层 datetime.now() 一致，aware / naive 不混用）。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 与 §7.2 batch_flow.flow_type 一一对应：收货加 / 分拣减 / 报损减 / 盘点调整
StockFlowTypeValue = Literal["receive_add", "pick_sub", "loss_sub", "count_adjust"]
# 与 §7.2 batch_flow.doc_type 一一对应：关联单据类型
StockDocTypeValue = Literal["purchase_order", "pick", "loss", "stock_count", "other"]


# --------------------------------------------------------------------------- 批次库存
class StockOut(BaseModel):
    """批次库存行（GET /stocks）：一段 = 门店 × SKU × 批次。

    qty_base 是基础单位数量；展示单位数量 = qty_base ÷ convert_factor，单位名取 unit。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    store_id: int = Field(description="0=总部仓，其余=门店ID")
    store_name: str | None = Field(default=None, description="门店名称；store_id=0 为「总部仓」")
    sku_id: int
    sku_no: str
    sku_name: str
    batch_no: str = Field(description="批次号，追溯主键")
    qty_base: Decimal = Field(description="结存数量（基础单位）")
    unit: str = Field(description="订货/展示单位（sku.unit）")
    convert_factor: Decimal = Field(description="1 展示单位 = 多少基础单位")
    expire_at: datetime = Field(description="保质期至")
    hours_to_expire: Decimal | None = Field(
        default=None, description="距到期小时数（2 位小数）；已过期为负值"
    )
    expiring: bool = Field(default=False, description="是否在临期阈值内（含已过期）")
    created_at: datetime | None = None


StockOutList = list[StockOut]


class StockPage(BaseModel):
    """批次库存分页响应：data={list,total,page,page_size}。"""

    list: StockOutList = Field(default_factory=list, description="当前页数据")
    total: int = Field(default=0, ge=0, description="总条数")
    page: int = Field(default=1, ge=1, description="当前页码")
    page_size: int = Field(default=20, ge=1, description="每页条数")


# --------------------------------------------------------------------------- 预警
class StockAlertItem(BaseModel):
    """低库存预警行（GET /stocks/alerts.low_stock）：按 SKU 聚合后结存低于阈值。"""

    sku_id: int
    sku_no: str
    sku_name: str
    qty_base: Decimal = Field(description="该范围内结存合计（基础单位）")
    unit: str = Field(description="订货/展示单位（sku.unit）")
    threshold: Decimal = Field(description="本次生效的低库存阈值（基础单位）")
    batch_count: int = Field(default=0, ge=0, description="仍有结存的批次数（qty_base>0）")


class StockAlertSummary(BaseModel):
    """预警汇总口径：计数为命中总数，不受 limit 截断（前端可显示「已展示 N / 共 M」）。"""

    expiring_count: int = Field(default=0, ge=0, description="临期批次命中总数")
    low_stock_count: int = Field(default=0, ge=0, description="低库存 SKU 命中总数")
    expire_hours: int = Field(description="本次临期判定窗口（小时）")
    low_qty_base: Decimal = Field(description="本次生效的低库存阈值（基础单位）")
    as_of: datetime = Field(description="快照时间（服务端当前时间）")


class StockAlertsOut(BaseModel):
    """临期与低库存预警（GET /stocks/alerts）：两条清单均受 limit 约束，无分页。"""

    expiring: list[StockOut] = Field(
        default_factory=list, description="临期批次清单（expire_at 升序，含已过期）"
    )
    low_stock: list[StockAlertItem] = Field(
        default_factory=list, description="低库存 SKU 清单（结存升序）"
    )
    summary: StockAlertSummary = Field(description="本次预警口径与命中总数")


# --------------------------------------------------------------------------- 批次流水
class StockFlowOut(BaseModel):
    """批次流水行（GET /stock-flows）：每次库存变动一行，仅追加、不可篡改。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    store_id: int = Field(description="0=总部仓，其余=门店ID")
    store_name: str | None = Field(default=None, description="门店名称；store_id=0 为「总部仓」")
    sku_id: int
    sku_no: str
    sku_name: str
    batch_no: str = Field(description="批次号，与 batch_stock.batch_no 同源")
    flow_type: StockFlowTypeValue = Field(description="收货加/分拣减/报损减/盘点调整")
    qty_change_base: Decimal = Field(description="变动量（基础单位）：加为正、减为负")
    qty_after_base: Decimal = Field(description="本次变动后结存（基础单位）")
    doc_type: StockDocTypeValue = Field(description="关联单据类型")
    doc_no: str = Field(description="关联单据号，人可读的追溯入口")
    operate_by: int = Field(description="操作人（逻辑外键→user.id）")
    occurred_at: datetime = Field(description="业务发生时间（非写入时间）")
    remark: str | None = None


StockFlowOutList = list[StockFlowOut]


class StockFlowPage(BaseModel):
    """批次流水分页响应：data={list,total,page,page_size}。"""

    list: StockFlowOutList = Field(default_factory=list, description="当前页数据")
    total: int = Field(default=0, ge=0, description="总条数")
    page: int = Field(default=1, ge=1, description="当前页码")
    page_size: int = Field(default=20, ge=1, description="每页条数")
