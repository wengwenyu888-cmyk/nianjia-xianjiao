"""配送与签收数据契约（§7.4 模型 + §8.2 配送签收组端点）。

约定：
- 请求体用 XxxIn / XxxCreate，响应体一律用 XxxOut（api 层禁止直接返回 ORM 对象）；
- 分页响应固定 {list,total,page,page_size}（§8.1）；字段名 list 会遮蔽内建 list，
  故列表注解统一用模块级别名（如 DeliveryOutList）；
- 状态值域与 §7.4 DDL 逐字一致：delivery = loaded/on_way/signed/partial/rejected，
  sign = full/partial/reject；状态流转只在 service 层做，请求体里不接受状态直改，
  签收状态缺省由明细差异推导，显式传入时必须在 service 层通过一致性校验。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# 与 §7.4 的 ENUM 一一对应
DeliveryStatus = Literal["loaded", "on_way", "signed", "partial", "rejected"]
SignStatus = Literal["full", "partial", "reject"]


# --------------------------------------------------------------------------- 配送单
class DeliveryItemIn(BaseModel):
    """装车明细行。pick_item_id 可省：省缺时 service 按 (summary_id, store_id) 派生批次。"""

    pick_item_id: int | None = Field(default=None, gt=0, description="来源分拣明细id(逻辑外键)")
    sku_id: int = Field(gt=0, description="逻辑外键→sku.id")
    batch_no: str = Field(min_length=1, max_length=32, description="批次号")
    qty_base: Decimal = Field(
        gt=0, max_digits=14, decimal_places=3, description="发送数量(基础单位)"
    )


class DeliveryCreate(BaseModel):
    """POST /deliveries 请求体（装车）。

    items 缺省时由 service 依据该汇总单下本门店的分拣明细（pick/pick_item）自动派生，
    批次号在此链条上「分拣落定 → 配送发送」保持一致。
    """

    summary_id: int = Field(gt=0, description="逻辑外键→summary.id")
    store_id: int = Field(gt=0, description="配送目标门店(逻辑外键→store.id)")
    require_date: date = Field(description="配送日 YYYY-MM-DD")
    driver_id: int | None = Field(default=None, gt=0, description="司机(逻辑外键→user.id)")
    plate_no: str | None = Field(default=None, max_length=16, description="车牌号")
    items: list[DeliveryItemIn] | None = Field(
        default=None, min_length=1, description="装车明细；缺省=按分拣明细派生"
    )


class DeliveryItemOut(BaseModel):
    """配送明细响应体。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    pick_item_id: int | None = None
    sku_id: int
    batch_no: str
    qty_base: Decimal


class DeliveryOut(BaseModel):
    """配送单响应体。列表接口 items 为空（防 N+1），详情接口带全量明细。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    delivery_no: str
    summary_id: int
    store_id: int
    require_date: date
    driver_id: int | None = None
    plate_no: str | None = None
    status: str
    loaded_at: datetime | None = None
    signed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    items: list[DeliveryItemOut] = Field(default_factory=list, description="配送明细")

    @classmethod
    def build(cls, delivery: Any, *, items: Sequence[Any] = ()) -> DeliveryOut:
        """由 ORM 实体装配响应体（api 层只调这里，不直接返回 ORM 对象）。"""
        return cls(
            id=delivery.id,
            delivery_no=delivery.delivery_no,
            summary_id=delivery.summary_id,
            store_id=delivery.store_id,
            require_date=delivery.require_date,
            driver_id=delivery.driver_id,
            plate_no=delivery.plate_no,
            status=delivery.status,
            loaded_at=delivery.loaded_at,
            signed_at=delivery.signed_at,
            created_at=delivery.created_at,
            updated_at=delivery.updated_at,
            items=[DeliveryItemOut.model_validate(item) for item in items],
        )


DeliveryOutList = list[DeliveryOut]


class DeliveryPage(BaseModel):
    """配送单分页响应：data={list,total,page,page_size}。"""

    list: DeliveryOutList = Field(default_factory=list, description="当前页数据")
    total: int = Field(default=0, ge=0, description="总条数")
    page: int = Field(default=1, ge=1, description="当前页码")
    page_size: int = Field(default=20, ge=1, description="每页条数")


# --------------------------------------------------------------------------- 签收单
class SignItemIn(BaseModel):
    """签收明细行：实收数量按基础单位上报，与配送明细 (sku_id, batch_no) 一一对应。"""

    sku_id: int = Field(gt=0, description="逻辑外键→sku.id")
    batch_no: str = Field(min_length=1, max_length=32, description="批次号")
    sign_qty_base: Decimal = Field(
        ge=0, max_digits=14, decimal_places=3, description="实收数量(基础单位)，0=整批未收"
    )


class SignIn(BaseModel):
    """POST /deliveries/{id}/sign 请求体（电子 POD，幂等）。

    items 必须覆盖该配送单的全部明细（按 sku_id+batch_no 对齐），缺行/多行一律 40000；
    status 缺省由明细差异推导：全部实收=full、全部为 0=reject、其余=partial，
    显式传入时 service 会校验与其一致性（不一致 40000）。
    """

    items: list[SignItemIn] = Field(min_length=1, description="实收明细，须覆盖配送单全部明细")
    sign_at: datetime | None = Field(default=None, description="签收时间，缺省取服务器当前时间")
    remark: str | None = Field(default=None, max_length=255, description="备注/差异说明")
    status: SignStatus | None = Field(default=None, description="缺省由明细差异推导")

    @model_validator(mode="after")
    def _check_no_duplicate_item(self) -> SignIn:
        seen: set[tuple[int, str]] = set()
        for item in self.items:
            key = (item.sku_id, item.batch_no)
            if key in seen:
                raise ValueError(f"签收明细重复：sku_id={key[0]}, batch_no={key[1]}")
            seen.add(key)
        return self


class SignItemOut(BaseModel):
    """签收明细响应体。diff_qty_base 为数据库生成列：正数=少送，负数=多收。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    sku_id: int
    batch_no: str
    send_qty_base: Decimal
    sign_qty_base: Decimal
    diff_qty_base: Decimal | None = None


class SignOut(BaseModel):
    """签收单响应体（GET /signs/{id}）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    delivery_id: int
    delivery_no: str | None = Field(default=None, description="关联配送单号，便于前端展示")
    store_id: int
    sign_by: int
    sign_at: datetime
    status: str
    remark: str | None = None
    created_at: datetime | None = None
    items: list[SignItemOut] = Field(default_factory=list, description="签收明细")

    @classmethod
    def build(
        cls, sign: Any, *, items: Sequence[Any] = (), delivery_no: str | None = None
    ) -> SignOut:
        """由 ORM 实体装配响应体。"""
        return cls(
            id=sign.id,
            delivery_id=sign.delivery_id,
            delivery_no=delivery_no,
            store_id=sign.store_id,
            sign_by=sign.sign_by,
            sign_at=sign.sign_at,
            status=sign.status,
            remark=sign.remark,
            created_at=sign.created_at,
            items=[SignItemOut.model_validate(item) for item in items],
        )
