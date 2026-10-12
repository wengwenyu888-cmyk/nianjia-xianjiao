"""汇总与分拣（§7.3 / §7.4）：汇总单 + 汇总明细 + 分拣单 + 分拣明细。

DDL 来源：docs/02-架构与模块设计.md v0.3.1 §7.3、§7.4。
职责分离：「汇总看量、分拣落批次」——批次分配只发生在分拣环节，按 expire_at 升序 FIFO。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import DECIMAL, Date, Enum, Index, Integer, String, UniqueConstraint, text
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


class Summary(Base, IdMixin, AuditMixin, SoftDeleteMixin):
    """汇总单（每配送日一张）。require_date 唯一：聚合任务重复触发也只落一张。"""

    __tablename__ = "summary"
    __table_args__ = (
        UniqueConstraint("summary_no", "deleted_at", name="uk_summary_no"),
        UniqueConstraint("require_date", "deleted_at", name="uk_req_date"),
        UniqueConstraint("idempotency_key", "deleted_at", name="uk_idem"),
        Index("idx_status", "status"),
        # 索引: uk_summary_no(summary_no, deleted_at) 用途: 汇总单号在未删除行内唯一。
        # 索引: uk_req_date(require_date, deleted_at)
        #   用途: 一个配送日只允许一张有效汇总单,聚合任务幂等。
        # 索引: uk_idem(idempotency_key, deleted_at) 用途: 生成接口重试不产生重复汇总单。
        # 索引: idx_status(status) 用途: 按状态推进分拣/配送流程(待分拣、配送中)。
        {**MYSQL_TABLE_OPTIONS, "comment": "汇总单(每配送日一张)"},
    )

    summary_no: Mapped[str] = mapped_column(String(32), nullable=False)
    require_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("generated", "picking", "picked", "delivering", "done", name="enum_summary_status"),
        nullable=False,
        server_default="generated",
    )
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    idempotency_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="生成请求幂等键"
    )


class SummaryItem(Base, IdMixin, AuditMixin):
    """汇总单明细（SKU×总量）。聚合写入天然幂等，随汇总单头失效、不单独软删。"""

    __tablename__ = "summary_item"
    __table_args__ = (
        UniqueConstraint("summary_id", "sku_id", name="uk_summary_sku"),
        # 索引: uk_summary_sku(summary_id, sku_id)
        #   用途: 同一汇总单内一个SKU只允许一行,聚合写入天然幂等。
        {**MYSQL_TABLE_OPTIONS, "comment": "汇总单明细(SKU×总量)"},
    )

    summary_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    sku_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    total_qty_base: Mapped[Decimal] = mapped_column(
        DECIMAL(14, 3), nullable=False, comment="该SKU当日要货总量(基础单位)"
    )


class Pick(Base, IdMixin, AuditMixin, SoftDeleteMixin):
    """分拣单（按门店）：一张汇总单按门店拆多张，分拣=批次落定环节。"""

    __tablename__ = "pick"
    __table_args__ = (
        UniqueConstraint("pick_no", "deleted_at", name="uk_pick_no"),
        UniqueConstraint("idempotency_key", "deleted_at", name="uk_idem"),
        Index("idx_summary_store", "summary_id", "store_id"),
        # 索引: uk_pick_no(pick_no, deleted_at) 用途: 分拣单号在未删除行内唯一。
        # 索引: uk_idem(idempotency_key, deleted_at) 用途: 生成分拣单接口重试不产生重复单据。
        # 索引: idx_summary_store(summary_id, store_id)
        #   用途: 按汇总单取各门店分拣单、校验同店未重复生成。
        {**MYSQL_TABLE_OPTIONS, "comment": "分拣单(按门店)"},
    )

    pick_no: Mapped[str] = mapped_column(String(32), nullable=False)
    summary_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    store_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False, comment="拣货目标门店")
    status: Mapped[str] = mapped_column(
        Enum("created", "picking", "done", "cancelled", name="enum_pick_status"),
        nullable=False,
        server_default="created",
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="生成请求幂等键"
    )
    version: Mapped[int] = mapped_column(
        INT_UNSIGNED, nullable=False, default=0, server_default=text("0")
    )


class PickItem(Base, IdMixin, AuditMixin):
    """分拣明细（批次在此落定）：FIFO 扣减 batch_stock 并写 batch_flow(pick_sub) 同事务完成。"""

    __tablename__ = "pick_item"
    __table_args__ = (
        Index("idx_pick", "pick_id"),
        Index("idx_sku_batch", "sku_id", "batch_no"),
        # 索引: idx_pick(pick_id) 用途: 按分拣单头取全部明细。
        # 索引: idx_sku_batch(sku_id, batch_no) 用途: 按SKU+批次反查被哪些分拣单拣出。
        {**MYSQL_TABLE_OPTIONS, "comment": "分拣明细(批次在此落定)"},
    )

    pick_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    sku_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    batch_no: Mapped[str] = mapped_column(String(32), nullable=False, comment="实际拣出的批次号")
    qty_base: Mapped[Decimal] = mapped_column(
        DECIMAL(14, 3), nullable=False, comment="拣出数量(基础单位)"
    )
