"""智能体建议数据契约（§8.2「智能体」组 + §7.3 agent_suggestion）。

规则版（rule-v1，不接真 LLM）：
- 建议依据（近 7 天要货均值、星期系数、总部库存与批次效期）以 JSON 快照落
  agent_suggestion.payload，便于回溯建议质量与统计采纳率；
- 「只建议不落账」：建议本身不产生有效单据；apply 只生成 draft 要货单，仍须店长 confirm；
- pick_plan 为只读 FIFO 预演，同样落 agent_suggestion（suggestion_type=pick_plan，store_id=0）。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# 与 §7.3 agent_suggestion.suggestion_type / apply_status 一一对应
SuggestionTypeValue = Literal["order_suggest", "pick_plan"]
ApplyStatusValue = Literal["pending", "applied", "rejected", "expired"]


class SuggestionGenerate(BaseModel):
    """POST /agent/order-suggestions 请求体：按店按日生成要货建议快照。"""

    store_id: int | None = Field(
        default=None, gt=0, description="建议对象门店；门店账号可省略（取本人 store_id）"
    )
    require_date: date = Field(description="需求配送日 YYYY-MM-DD")


class SuggestionOut(BaseModel):
    """建议快照响应体：payload 即生成当时的依据快照（销量/库存/效期/理由）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    suggestion_type: SuggestionTypeValue
    store_id: int = Field(description="建议对象门店，0=总部/全局")
    require_date: date | None = None
    payload: dict[str, Any] = Field(default_factory=dict, description="建议明细与依据快照")
    apply_status: ApplyStatusValue = Field(description="应用状态")
    applied_by: int | None = Field(default=None, description="采纳人")
    applied_at: datetime | None = None
    order_id: int | None = Field(default=None, description="apply 生成的 draft 要货单 id")
    model: str | None = Field(default=None, description="生成所用规则/提示词版本")
    version: int | None = Field(default=None, description="乐观锁版本令牌")
    created_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


SuggestionOutList = list[SuggestionOut]


class SuggestionPage(BaseModel):
    """建议快照分页响应（§8.2 暂无 GET 列表端点，契约先行，供治理看板复用）。"""

    list: SuggestionOutList = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1)


class PickPlanRequest(BaseModel):
    """POST /agent/pick-plan 请求体：按配送日做 FIFO 批次预演（只读，不扣库存）。"""

    require_date: date = Field(description="需求配送日 YYYY-MM-DD")


class PickPlanBatchOut(BaseModel):
    """预演命中的批次行（只读快照，不产生任何库存变动）。"""

    batch_no: str
    qty_base: Decimal = Field(description="预演分配数量（基础单位）")
    expire_at: datetime | None = Field(default=None, description="该批次保质期至")
    produced_at: date | None = Field(default=None, description="该批次生产日期")


class PickPlanTaskOut(BaseModel):
    """预演任务行：门店×SKU 的需求量与 FIFO 批次分配结果。"""

    store_id: int
    sku_id: int
    required_qty_base: Decimal = Field(description="该门店该 SKU 当日要货量（基础单位）")
    allocated_qty_base: Decimal = Field(description="预演可分配量（基础单位）")
    shortage_qty_base: Decimal = Field(description="预演缺口（基础单位），>0 表示总部仓不足")
    batches: list[PickPlanBatchOut] = Field(default_factory=list, description="FIFO 批次预演明细")
    flags: list[str] = Field(default_factory=list, description="风险提示（临期批次/缺口等）")


class PickPlanOut(BaseModel):
    """配货/分拣批次计划响应体（同时是 agent_suggestion.payload 的形状）。"""

    suggestion_id: int = Field(description="本次预演落库的建议快照 id")
    require_date: date
    policy: str = Field(description="生成策略版本，如 rule-v1")
    generated_at: datetime = Field(description="生成时间")
    tasks: list[PickPlanTaskOut] = Field(default_factory=list)
    warnings: list[str] = Field(
        default_factory=list, description="全局提示（如当日无已确认要货单）"
    )
    total_required_qty_base: Decimal = Field(default=Decimal("0"))
    total_shortage_qty_base: Decimal = Field(default=Decimal("0"))
