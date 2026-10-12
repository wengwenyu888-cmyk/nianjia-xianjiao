"""主数据（§7.1）：门店 / 供应商 / 商品 SKU / 价目表。

DDL 来源：docs/02-架构与模块设计.md v0.3.1 §7.1。
逻辑外键：sku_id 等只写注释，不建物理外键（§7 通用约定：性能 / 在线 DDL / 归档）。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import DECIMAL, Date, Enum, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.model.base import (
    BIGINT_UNSIGNED,
    MYSQL_TABLE_OPTIONS,
    TINYINT,
    AuditMixin,
    Base,
    IdMixin,
    SoftDeleteMixin,
)


class Store(Base, IdMixin, AuditMixin, SoftDeleteMixin):
    """门店。delivery_cycle 决定要货节奏，驱动每日汇总定时任务。"""

    __tablename__ = "store"
    __table_args__ = (
        UniqueConstraint("store_no", "deleted_at", name="uk_store_no"),
        # 索引: uk_store_no(store_no, deleted_at)
        #   用途: 门店编码在"未删除行"内唯一,软删后可重开同一编码。
        {**MYSQL_TABLE_OPTIONS, "comment": "门店"},
    )

    store_no: Mapped[str] = mapped_column(String(32), nullable=False, comment="门店编码")
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="门店名称")
    region: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="区域/城市")
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    delivery_cycle: Mapped[str] = mapped_column(
        Enum("daily", "every_other_day", name="enum_store_delivery_cycle"),
        nullable=False,
        server_default="daily",
        comment="配送节奏:日配/隔日配",
    )
    status: Mapped[int] = mapped_column(
        TINYINT, nullable=False, server_default=text("1"), comment="1营业 0停业"
    )


class Supplier(Base, IdMixin, AuditMixin, SoftDeleteMixin):
    """供应商。payment_terms 账期驱动应付与对账周期。"""

    __tablename__ = "supplier"
    __table_args__ = (
        UniqueConstraint("supplier_no", "deleted_at", name="uk_supplier_no"),
        # 索引: uk_supplier_no(supplier_no, deleted_at)
        #   用途: 供应商编码在未删除行内唯一,软删后可复用编码。
        {**MYSQL_TABLE_OPTIONS, "comment": "供应商"},
    )

    supplier_no: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payment_terms: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), comment="账期(天)"
    )
    status: Mapped[int] = mapped_column(TINYINT, nullable=False, server_default=text("1"))


class Sku(Base, IdMixin, AuditMixin, SoftDeleteMixin):
    """商品 SKU：base_unit + convert_factor 统一多单位换算；shelf_life_hours 支撑效期预警。"""

    __tablename__ = "sku"
    __table_args__ = (
        UniqueConstraint("sku_no", "deleted_at", name="uk_sku_no"),
        Index("idx_category", "category"),
        # 索引: uk_sku_no(sku_no, deleted_at) 用途: SKU 编码在未删除行内唯一,软删后可复用编码。
        # 索引: idx_category(category) 用途: 总部按品类筛选与统计(B端列表默认筛选)。
        {**MYSQL_TABLE_OPTIONS, "comment": "商品SKU"},
    )

    sku_no: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="品名")
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="馅料-肉馅/馅料-海鲜/面皮/调料/包材/鲜活"
    )
    spec: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="规格描述,如5kg/袋")
    unit: Mapped[str] = mapped_column(String(16), nullable=False, comment="订货/展示单位,如袋")
    base_unit: Mapped[str] = mapped_column(String(16), nullable=False, comment="基础计算单位,如kg")
    convert_factor: Mapped[Decimal] = mapped_column(
        DECIMAL(12, 4), nullable=False, server_default=text("1"), comment="1订货单位=多少基础单位"
    )
    shelf_life_hours: Mapped[int] = mapped_column(Integer, nullable=False, comment="保质期(小时)")
    supply_type: Mapped[str] = mapped_column(
        Enum("direct", "temp", name="enum_sku_supply_type"),
        nullable=False,
        server_default="direct",
        comment="直配/临采",
    )
    status: Mapped[int] = mapped_column(TINYINT, nullable=False, server_default=text("1"))


class Price(Base, IdMixin, AuditMixin, SoftDeleteMixin):
    """价目表（含历史版本）：价格带生效区间、只增不改，对账须能取任意历史日期的当时价。"""

    __tablename__ = "price"
    __table_args__ = (
        UniqueConstraint(
            "sku_id", "price_type", "effective_from", "deleted_at", name="uk_sku_type_from"
        ),
        Index("idx_sku_eff", "sku_id", "effective_from", "effective_to"),
        # 索引: uk_sku_type_from(sku_id, price_type, effective_from, deleted_at)
        #   用途: 同一SKU同类型价在同一天只允许一条有效记录,软删后可重录。
        # 索引: idx_sku_eff(sku_id, effective_from, effective_to)
        #   用途: 按日期区间取"当时价"的对账查询路径。
        {**MYSQL_TABLE_OPTIONS, "comment": "价目表(含历史版本)"},
    )

    sku_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False, comment="逻辑外键→sku.id")
    price_type: Mapped[str] = mapped_column(
        Enum("purchase", "transfer", name="enum_price_type"),
        nullable=False,
        comment="采购价/内部调拨价",
    )
    price: Mapped[Decimal] = mapped_column(
        DECIMAL(12, 4), nullable=False, comment="单价(元/订货单位)"
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True, comment="NULL=现行有效")
