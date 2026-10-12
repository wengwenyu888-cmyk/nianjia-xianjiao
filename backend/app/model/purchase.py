"""采购（§7.2）：采购单头 + 明细。

DDL 来源：docs/02-架构与模块设计.md v0.3.1 §7.2。
收货时在服务层同一事务内「生成批次库存 batch_stock + 写 batch_flow(receive_add)」。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DECIMAL, DateTime, Enum, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.model.base import (
    BIGINT_UNSIGNED,
    INT_UNSIGNED,
    MYSQL_TABLE_OPTIONS,
    AuditMixin,
    Base,
    IdMixin,
    SoftDeleteMixin,
)


class PurchaseOrder(Base, IdMixin, AuditMixin, SoftDeleteMixin):
    """采购单头。状态机 draft→submitted→received 驱动收货；uk_idem 防重复建单。"""

    __tablename__ = "purchase_order"
    __table_args__ = (
        UniqueConstraint("po_no", "deleted_at", name="uk_po_no"),
        UniqueConstraint("idempotency_key", "deleted_at", name="uk_idem"),
        Index("idx_supplier_status", "supplier_id", "status"),
        # 索引: uk_po_no(po_no, deleted_at) 用途: 采购单号在未删除行内唯一,软删后号段可复用。
        # 索引: uk_idem(idempotency_key, deleted_at)
        #   用途: 幂等键防重复建单;键为 NULL 时不约束(等价未启用幂等)。
        # 索引: idx_supplier_status(supplier_id, status) 用途: 按供应商查在途/待收货采购单。
        {**MYSQL_TABLE_OPTIONS, "comment": "采购单头"},
    )

    po_no: Mapped[str] = mapped_column(String(32), nullable=False)
    supplier_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    store_id: Mapped[int] = mapped_column(
        BIGINT_UNSIGNED, nullable=False, server_default=text("0"), comment="收货点,0=总部仓"
    )
    status: Mapped[str] = mapped_column(
        Enum("draft", "submitted", "received", "cancelled", name="enum_purchase_order_status"),
        nullable=False,
        server_default="draft",
    )
    expect_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="预计到货")
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="幂等键")
    version: Mapped[int] = mapped_column(
        INT_UNSIGNED, nullable=False, default=0, server_default=text("0")
    )


class PurchaseOrderItem(Base, IdMixin, AuditMixin):
    """采购单明细。数量三件套 + received_qty_base 支持分批收货；随头行存在、不单独软删。"""

    __tablename__ = "purchase_order_item"
    __table_args__ = (
        Index("idx_po", "po_id"),
        Index("idx_sku", "sku_id"),
        # 索引: idx_po(po_id) 用途: 按采购单头取全部明细。
        # 索引: idx_sku(sku_id) 用途: 按SKU反查采购历史与到货情况。
        {**MYSQL_TABLE_OPTIONS, "comment": "采购单明细"},
    )

    po_id: Mapped[int] = mapped_column(
        BIGINT_UNSIGNED, nullable=False, comment="逻辑外键→purchase_order.id"
    )
    sku_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    qty_base: Mapped[Decimal] = mapped_column(DECIMAL(14, 3), nullable=False)
    qty_unit: Mapped[Decimal] = mapped_column(
        DECIMAL(14, 3), nullable=False, comment="展示单位数量"
    )
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    price: Mapped[Decimal] = mapped_column(
        DECIMAL(12, 4), nullable=False, comment="下单单价(元/展示单位)"
    )
    received_qty_base: Mapped[Decimal] = mapped_column(
        DECIMAL(14, 3), nullable=False, server_default=text("0"), comment="已收数量(基础单位)"
    )
