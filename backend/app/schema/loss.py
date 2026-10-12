"""报损数据契约（§7.5 模型 + §8.2 报损组端点）。

约定：
- 请求体用 XxxCreate，响应体一律用 XxxOut（api 层禁止直接返回 ORM 对象）；
- 分页响应固定 {list,total,page,page_size}（§8.1）；
- 值域与 §7.5 DDL 逐字一致：type = expire/damage/count_diff，status = draft/approved；
  审批通过才扣减批次库存（status 由 service 流转，请求体不接受状态）。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 与 §7.5 的 ENUM 一一对应
LossType = Literal["expire", "damage", "count_diff"]
LossStatus = Literal["draft", "approved"]


class LossCreate(BaseModel):
    """POST /losses 请求体（门店提交报损）。

    store_id 缺省取当前门店账号的 store_id（门店账号强制本店，跨店 40300）；
    总部账号（store_id 为空）必须显式传 store_id。
    """

    store_id: int | None = Field(default=None, gt=0, description="门店id；门店账号可缺省=本店")
    sku_id: int = Field(gt=0, description="逻辑外键→sku.id")
    batch_no: str | None = Field(
        default=None, max_length=32, description="批次号；缺省=审批时按 FIFO 跨批次扣减"
    )
    qty_base: Decimal = Field(
        gt=0, max_digits=14, decimal_places=3, description="报损数量(基础单位)"
    )
    type: LossType = Field(description="临期报损/破损/盘点差异")
    reason: str | None = Field(default=None, max_length=255, description="报损原因")


class LossOut(BaseModel):
    """报损单响应体。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    loss_no: str
    store_id: int
    sku_id: int
    batch_no: str | None = None
    qty_base: Decimal
    type: str
    reason: str | None = None
    status: str
    approved_by: int | None = None
    approved_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


LossOutList = list[LossOut]


class LossPage(BaseModel):
    """报损单分页响应：data={list,total,page,page_size}。"""

    list: LossOutList = Field(default_factory=list, description="当前页数据")
    total: int = Field(default=0, ge=0, description="总条数")
    page: int = Field(default=1, ge=1, description="当前页码")
    page_size: int = Field(default=20, ge=1, description="每页条数")
