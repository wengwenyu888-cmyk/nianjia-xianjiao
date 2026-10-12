"""主数据数据契约（§8.2）：门店 / SKU / 供应商 / 价目。

约定：
- 请求体用 XxxCreate / XxxUpdate，响应体一律用 XxxOut（api 层禁止直接返回 ORM 对象）；
- 分页响应固定 {list, total, page, page_size}（§8.1），不复用通用 Page（其形状为 items/meta）；
- 主数据表（§7.1）没有 version 列，乐观锁版本令牌回退为 updated_at 的 Unix 毫秒，
  更新请求回传 version，不一致由 service 返回 40900。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# 与 §7.1 的 ENUM 一一对应
DeliveryCycle = Literal["daily", "every_other_day"]
SupplyType = Literal["direct", "temp"]
PriceType = Literal["purchase", "transfer"]


class VersionedOut(BaseModel):
    """带乐观锁版本令牌的响应基类：优先实体 version 列，否则取 updated_at 毫秒。"""

    model_config = ConfigDict(from_attributes=True)

    updated_at: datetime | None = Field(default=None, description="最后更新时间")
    version: int | None = Field(default=None, description="乐观锁版本令牌")

    @model_validator(mode="before")
    @classmethod
    def _attach_version(cls, data: Any) -> Any:
        """从 ORM 实体推导版本令牌（dict 入参原样透传）。"""
        if isinstance(data, dict):
            return data
        raw_version = getattr(data, "version", None)
        updated_at = getattr(data, "updated_at", None)
        if raw_version is not None:
            token = int(raw_version)
        elif isinstance(updated_at, datetime):
            token = int(updated_at.timestamp() * 1000)
        else:
            return data
        return {name: getattr(data, name, None) for name in cls.model_fields} | {"version": token}


# --------------------------------------------------------------------------- 门店
class StoreCreate(BaseModel):
    """POST /stores 请求体。"""

    store_no: str = Field(min_length=1, max_length=32, description="门店编码")
    name: str = Field(min_length=1, max_length=64, description="门店名称")
    region: str | None = Field(default=None, max_length=64, description="区域/城市")
    address: str | None = Field(default=None, max_length=255)
    contact_name: str | None = Field(default=None, max_length=32)
    contact_phone: str | None = Field(default=None, max_length=32)
    delivery_cycle: DeliveryCycle = Field(default="daily", description="配送节奏:日配/隔日配")
    status: int = Field(default=1, ge=0, le=1, description="1营业 0停业")


class StoreUpdate(BaseModel):
    """PUT /stores/{id} 请求体：门店编码不可改，只改配送节奏等运营字段。"""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    region: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=255)
    contact_name: str | None = Field(default=None, max_length=32)
    contact_phone: str | None = Field(default=None, max_length=32)
    delivery_cycle: DeliveryCycle | None = None
    status: int | None = Field(default=None, ge=0, le=1)
    version: int | None = Field(default=None, description="乐观锁版本令牌，来自 GET 的 version")


class StoreOut(VersionedOut):
    """门店响应体。"""

    id: int
    store_no: str
    name: str
    region: str | None = None
    address: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    delivery_cycle: str
    status: int
    created_at: datetime | None = None


# --------------------------------------------------------------------------- SKU
class SkuCreate(BaseModel):
    """POST /skus 请求体：单位/换算/保质期一次落齐。"""

    sku_no: str = Field(min_length=1, max_length=32, description="SKU 编码")
    name: str = Field(min_length=1, max_length=64, description="品名")
    category: str = Field(min_length=1, max_length=32, description="品类")
    spec: str | None = Field(default=None, max_length=64, description="规格描述,如5kg/袋")
    unit: str = Field(min_length=1, max_length=16, description="订货/展示单位,如袋")
    base_unit: str = Field(min_length=1, max_length=16, description="基础计算单位,如kg")
    convert_factor: Decimal = Field(
        default=Decimal("1"),
        gt=0,
        max_digits=12,
        decimal_places=4,
        description="1订货单位=多少基础单位",
    )
    shelf_life_hours: int = Field(ge=0, description="保质期(小时)")
    supply_type: SupplyType = Field(default="direct", description="直配/临采")
    status: int = Field(default=1, ge=0, le=1)


class SkuUpdate(BaseModel):
    """SKU 更新请求体（§8.2 未开放 PUT /skus，供 service 内部与后续扩展使用）。"""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    category: str | None = Field(default=None, min_length=1, max_length=32)
    spec: str | None = Field(default=None, max_length=64)
    unit: str | None = Field(default=None, min_length=1, max_length=16)
    base_unit: str | None = Field(default=None, min_length=1, max_length=16)
    convert_factor: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=4)
    shelf_life_hours: int | None = Field(default=None, ge=0)
    supply_type: SupplyType | None = None
    status: int | None = Field(default=None, ge=0, le=1)
    version: int | None = Field(default=None, description="乐观锁版本令牌")


class SkuOut(VersionedOut):
    """SKU 响应体。"""

    id: int
    sku_no: str
    name: str
    category: str
    spec: str | None = None
    unit: str
    base_unit: str
    convert_factor: Decimal
    shelf_life_hours: int
    supply_type: str
    status: int
    created_at: datetime | None = None


# --------------------------------------------------------------------------- 供应商
class SupplierCreate(BaseModel):
    """POST /suppliers 请求体。"""

    supplier_no: str = Field(min_length=1, max_length=32, description="供应商编码")
    name: str = Field(min_length=1, max_length=64)
    contact_name: str | None = Field(default=None, max_length=32)
    contact_phone: str | None = Field(default=None, max_length=32)
    payment_terms: int = Field(default=0, ge=0, description="账期(天)")
    status: int = Field(default=1, ge=0, le=1)


class SupplierUpdate(BaseModel):
    """供应商更新请求体（§8.2 未开放 PUT /suppliers）。"""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    contact_name: str | None = Field(default=None, max_length=32)
    contact_phone: str | None = Field(default=None, max_length=32)
    payment_terms: int | None = Field(default=None, ge=0)
    status: int | None = Field(default=None, ge=0, le=1)
    version: int | None = Field(default=None, description="乐观锁版本令牌")


class SupplierOut(VersionedOut):
    """供应商响应体。"""

    id: int
    supplier_no: str
    name: str
    contact_name: str | None = None
    contact_phone: str | None = None
    payment_terms: int
    status: int
    created_at: datetime | None = None


# --------------------------------------------------------------------------- 价目
class PriceCreate(BaseModel):
    """POST /prices 请求体：价格带生效区间、只增不改。"""

    sku_id: int = Field(gt=0, description="逻辑外键→sku.id")
    price_type: PriceType = Field(description="采购价/内部调拨价")
    price: Decimal = Field(gt=0, max_digits=12, decimal_places=4, description="单价(元/订货单位)")
    effective_from: date
    effective_to: date | None = Field(default=None, description="NULL=现行有效")

    @model_validator(mode="after")
    def _check_effective_range(self) -> Self:
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to 不能早于 effective_from")
        return self


class PriceOut(VersionedOut):
    """价目响应体。"""

    id: int
    sku_id: int
    price_type: str
    price: Decimal
    effective_from: date
    effective_to: date | None = None
    created_at: datetime | None = None


# --------------------------------------------------------------------------- 分页响应
# 说明：字段名 list 与 §8.1 契约一致；注解用模块级别名，避免类命名空间里的
# list 字段遮蔽内建 list（否则 pydantic 无法求值 list[...] 注解）。
StoreOutList = list[StoreOut]


class StorePage(BaseModel):
    """门店分页响应：data={list,total,page,page_size}。"""

    list: StoreOutList = Field(default_factory=list, description="当前页数据")
    total: int = Field(default=0, ge=0, description="总条数")
    page: int = Field(default=1, ge=1, description="当前页码")
    page_size: int = Field(default=20, ge=1, description="每页条数")


SkuOutList = list[SkuOut]


class SkuPage(BaseModel):
    """SKU 分页响应。"""

    list: SkuOutList = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1)


SupplierOutList = list[SupplierOut]


class SupplierPage(BaseModel):
    """供应商分页响应。"""

    list: SupplierOutList = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1)


PriceOutList = list[PriceOut]


class PricePage(BaseModel):
    """价目分页响应。"""

    list: PriceOutList = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1)
