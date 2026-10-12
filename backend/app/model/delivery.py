"""配送与签收（§7.4）：配送单 / 配送明细 / 签收单 / 签收明细。

DDL 来源：docs/02-架构与模块设计.md v0.3.1 §7.4。
签收单不做软删除（签收即事实，只能冲正不能删），故 uk_idem 不与 deleted_at 组合。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    DECIMAL,
    Computed,
    Date,
    DateTime,
    Enum,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.model.base import (
    BIGINT_UNSIGNED,
    MYSQL_TABLE_OPTIONS,
    AuditMixin,
    Base,
    IdMixin,
    SoftDeleteMixin,
)


class Delivery(Base, IdMixin, AuditMixin, SoftDeleteMixin):
    """配送单（一车一店一单）：状态机 loaded→on_way→signed/partial/rejected。"""

    __tablename__ = "delivery"
    __table_args__ = (
        UniqueConstraint("delivery_no", "deleted_at", name="uk_delivery_no"),
        UniqueConstraint("idempotency_key", "deleted_at", name="uk_idem"),
        Index("idx_driver_date", "driver_id", "require_date"),
        Index("idx_summary", "summary_id"),
        # 索引: uk_delivery_no(delivery_no, deleted_at) 用途: 配送单号在未删除行内唯一。
        # 索引: uk_idem(idempotency_key, deleted_at) 用途: 生成配送单接口重试不产生重复单据。
        # 索引: idx_driver_date(driver_id, require_date) 用途: 司机小程序查当日任务列表。
        # 索引: idx_summary(summary_id) 用途: 按汇总单查其拆出的配送单。
        {**MYSQL_TABLE_OPTIONS, "comment": "配送单(一车一店一单)"},
    )

    delivery_no: Mapped[str] = mapped_column(String(32), nullable=False)
    summary_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    store_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    require_date: Mapped[date] = mapped_column(Date, nullable=False)
    driver_id: Mapped[int | None] = mapped_column(
        BIGINT_UNSIGNED, nullable=True, comment="司机(逻辑外键→user.id)"
    )
    plate_no: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("loaded", "on_way", "signed", "partial", "rejected", name="enum_delivery_status"),
        nullable=False,
        server_default="loaded",
    )
    loaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="生成请求幂等键"
    )


class DeliveryItem(Base, IdMixin, AuditMixin):
    """配送明细。pick_item_id 溯源：配送明细→分拣明细→要货单明细，单据链闭合。"""

    __tablename__ = "delivery_item"
    __table_args__ = (
        Index("idx_delivery", "delivery_id"),
        Index("idx_pick_item", "pick_item_id"),
        # 索引: idx_delivery(delivery_id) 用途: 按配送单头取全部明细。
        # 索引: idx_pick_item(pick_item_id) 用途: 由分拣明细反查配送去向,支撑单据链追溯。
        {**MYSQL_TABLE_OPTIONS, "comment": "配送明细"},
    )

    delivery_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    pick_item_id: Mapped[int | None] = mapped_column(
        BIGINT_UNSIGNED, nullable=True, comment="来源分拣明细"
    )
    sku_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    batch_no: Mapped[str] = mapped_column(String(32), nullable=False)
    qty_base: Mapped[Decimal] = mapped_column(
        DECIMAL(14, 3), nullable=False, comment="发送数量(基础单位)"
    )


class Sign(Base, IdMixin, AuditMixin):
    """签收单（电子 POD）。uk_delivery 强制与配送单 1:1；不做软删除。"""

    __tablename__ = "sign"
    __table_args__ = (
        UniqueConstraint("delivery_id", name="uk_delivery"),
        UniqueConstraint("idempotency_key", name="uk_idem"),
        # 索引: uk_delivery(delivery_id) 用途: 配送单与签收单 1:1,防重复签收。
        # 索引: uk_idem(idempotency_key) 用途: 签收接口重试幂等;
        #   无软删故不加 deleted_at 列,NULL 不约束。
        {**MYSQL_TABLE_OPTIONS, "comment": "签收单(电子POD)"},
    )

    delivery_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    store_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    sign_by: Mapped[int] = mapped_column(
        BIGINT_UNSIGNED, nullable=False, comment="签收人(店长/店员)"
    )
    sign_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("full", "partial", "reject", name="enum_sign_status"),
        nullable=False,
        server_default="full",
    )
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)


class SignItem(Base, IdMixin, AuditMixin):
    """签收明细。差异生成列：正数=少送(进对账)，负数=多收(异常)，由数据库计算保证一致。"""

    __tablename__ = "sign_item"
    __table_args__ = (
        Index("idx_sign", "sign_id"),
        # 索引: idx_sign(sign_id) 用途: 按签收单头取全部明细并核对差异。
        {**MYSQL_TABLE_OPTIONS, "comment": "签收明细"},
    )

    sign_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    sku_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    batch_no: Mapped[str] = mapped_column(String(32), nullable=False)
    send_qty_base: Mapped[Decimal] = mapped_column(
        DECIMAL(14, 3), nullable=False, comment="应送数量(基础单位)"
    )
    sign_qty_base: Mapped[Decimal] = mapped_column(
        DECIMAL(14, 3), nullable=False, comment="实收数量(基础单位)"
    )
    diff_qty_base: Mapped[Decimal | None] = mapped_column(
        DECIMAL(14, 3),
        Computed("send_qty_base - sign_qty_base", persisted=True),
        nullable=True,
        comment="差异=应送-实收",
    )
