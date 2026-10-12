"""报损与对账（§7.5）：报损单 + 对账单。

DDL 来源：docs/02-架构与模块设计.md v0.3.1 §7.5。
报损审批通过后扣减批次库存，且必须在同一事务内写 batch_flow（loss_sub / count_adjust）。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DECIMAL, DateTime, Enum, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.model.base import (
    BIGINT_UNSIGNED,
    MYSQL_TABLE_OPTIONS,
    AuditMixin,
    Base,
    IdMixin,
    SoftDeleteMixin,
)


class Loss(Base, IdMixin, AuditMixin, SoftDeleteMixin):
    """报损单。损耗率 KPI 数据源（按门店×SKU×周期聚合 qty_base）；挂批次保证库存去向可解释。"""

    __tablename__ = "loss"
    __table_args__ = (
        UniqueConstraint("loss_no", "deleted_at", name="uk_loss_no"),
        UniqueConstraint("idempotency_key", "deleted_at", name="uk_idem"),
        Index("idx_store_sku", "store_id", "sku_id"),
        Index("idx_store_created", "store_id", "created_at"),
        # 索引: uk_loss_no(loss_no, deleted_at) 用途: 报损单号在未删除行内唯一。
        # 索引: uk_idem(idempotency_key, deleted_at) 用途: 门店提交报损重试不产生重复单。
        # 索引: idx_store_sku(store_id, sku_id) 用途: 按门店×SKU 聚合损耗率 KPI。
        # 索引: idx_store_created(store_id, created_at) 用途: 门店按时间窗查报损记录与总部审批列表。
        {**MYSQL_TABLE_OPTIONS, "comment": "报损单"},
    )

    loss_no: Mapped[str] = mapped_column(String(32), nullable=False)
    store_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    sku_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    batch_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    qty_base: Mapped[Decimal] = mapped_column(DECIMAL(14, 3), nullable=False)
    type: Mapped[str] = mapped_column(
        Enum("expire", "damage", "count_diff", name="enum_loss_type"),
        nullable=False,
        comment="临期报损/破损/盘点差异",
    )
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("draft", "approved", name="enum_loss_status"),
        nullable=False,
        server_default="draft",
    )
    approved_by: Mapped[int | None] = mapped_column(BIGINT_UNSIGNED, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="提交请求幂等键"
    )


class Reconcile(Base, IdMixin, AuditMixin, SoftDeleteMixin):
    """对账单（门店×周期）。双轨并行期间与管家婆逐店对账，差异落 diff_amount。"""

    __tablename__ = "reconcile"
    __table_args__ = (
        UniqueConstraint("store_id", "period", "deleted_at", name="uk_store_period"),
        UniqueConstraint("idempotency_key", "deleted_at", name="uk_idem"),
        # 索引: uk_store_period(store_id, period, deleted_at)
        #   用途: 同一门店同一周期只允许一张有效对账单。
        # 索引: uk_idem(idempotency_key, deleted_at) 用途: 生成对账单任务重跑不产生重复单。
        {**MYSQL_TABLE_OPTIONS, "comment": "对账单(门店×周期)"},
    )

    period: Mapped[str] = mapped_column(String(16), nullable=False, comment="对账周期,如2026-W42")
    store_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(
        DECIMAL(14, 2), nullable=False, server_default=text("0"), comment="本周期内部结算额(元)"
    )
    diff_amount: Mapped[Decimal] = mapped_column(
        DECIMAL(14, 2),
        nullable=False,
        server_default=text("0"),
        comment="与外部台账(管家婆)差异额",
    )
    status: Mapped[str] = mapped_column(
        Enum("draft", "confirmed", "done", name="enum_reconcile_status"),
        nullable=False,
        server_default="draft",
    )
    confirmed_by: Mapped[int | None] = mapped_column(BIGINT_UNSIGNED, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="生成请求幂等键"
    )
