"""汇总与分拣数据契约（§8.2「汇总分拣」组 + §7.3 summary/summary_item、§7.4 pick/pick_item）。

约定：
- 汇总只到 SKU 维度（summary_item.total_qty_base），批次分配发生在分拣环节；
- 分页响应固定 {list, total, page, page_size}（§8.1）；
- 状态机值域与 DDL 一一对应，流转只在 service 层发生。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# 与 §7.3 summary.status 一一对应
SummaryStatusValue = Literal["generated", "picking", "picked", "delivering", "done"]
# 与 §7.4 pick.status 一一对应
PickStatusValue = Literal["created", "picking", "done", "cancelled"]


class SummaryGenerate(BaseModel):
    """POST /summaries/generate 请求体：一个配送日只允许一张有效汇总单（uk_req_date）。"""

    require_date: date = Field(description="需求配送日 YYYY-MM-DD")


class SummaryItemOut(BaseModel):
    """汇总明细响应体（SKU×当日要货总量）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    summary_id: int
    sku_id: int
    total_qty_base: Decimal = Field(description="该 SKU 当日要货总量（基础单位）")


class SummaryOut(BaseModel):
    """汇总单响应体：头 + SKU 汇总明细（items 由 service 装配）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    summary_no: str
    require_date: date
    status: SummaryStatusValue
    line_count: int = Field(default=0, ge=0, description="汇总行数（SKU 数）")
    idempotency_key: str | None = None
    created_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    items: list[SummaryItemOut] = Field(default_factory=list, description="SKU 汇总明细")

    @model_validator(mode="before")
    @classmethod
    def _project_items(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return data
        payload = {name: getattr(data, name, None) for name in cls.model_fields}
        raw_items = getattr(data, "items", None) or ()
        payload["items"] = [SummaryItemOut.model_validate(row) for row in raw_items]
        return payload


SummaryOutList = list[SummaryOut]


class SummaryPage(BaseModel):
    """汇总单分页响应：data={list,total,page,page_size}。"""

    list: SummaryOutList = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1)


class PickCreate(BaseModel):
    """POST /picks 请求体：按门店生成分拣单（FIFO 锁定并扣减总部仓批次库存）。"""

    summary_id: int = Field(gt=0, description="逻辑外键→summary.id")
    store_id: int = Field(gt=0, description="拣货目标门店 id")


class PickItemOut(BaseModel):
    """分拣明细响应体（批次在此落定）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    pick_id: int
    sku_id: int
    batch_no: str = Field(description="实际拣出的批次号")
    qty_base: Decimal = Field(description="拣出数量（基础单位）")


class PickOut(BaseModel):
    """分拣单响应体：头 + 批次明细（items 由 service 装配）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    pick_no: str
    summary_id: int
    store_id: int
    status: PickStatusValue
    version: int | None = Field(default=None, description="乐观锁版本令牌")
    idempotency_key: str | None = None
    created_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    items: list[PickItemOut] = Field(default_factory=list, description="分拣批次明细")

    @model_validator(mode="before")
    @classmethod
    def _project_items(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return data
        payload = {name: getattr(data, name, None) for name in cls.model_fields}
        raw_items = getattr(data, "items", None) or ()
        payload["items"] = [PickItemOut.model_validate(row) for row in raw_items]
        return payload


PickOutList = list[PickOut]


class PickPage(BaseModel):
    """分拣单分页响应（§8.2 暂无 GET /picks 端点，契约先行，供配送环节与前端复用）。"""

    list: PickOutList = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1)
