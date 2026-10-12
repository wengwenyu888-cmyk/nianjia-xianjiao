"""库存（§7.2）：批次库存结存表 + 批次流水台账。

DDL 来源：docs/02-架构与模块设计.md v0.3.1 §7.2。
可追溯 = 流水 + 结存双轨：batch_stock 只存当前结存，batch_flow 记录每一笔变动
（谁操作、依据哪张单），两者必须在服务层同一事务内写入。
batch_flow 仅追加（append-only）：无 deleted_at，记错只能写反向冲正流水。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import DECIMAL, Date, DateTime, Enum, Index, String, UniqueConstraint, text
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


class BatchStock(Base, IdMixin, AuditMixin, SoftDeleteMixin):
    """批次库存（结存表）：库存按 门店×批次 隔离，结存行供 SELECT ... FOR UPDATE 行锁扣减。"""

    __tablename__ = "batch_stock"
    __table_args__ = (
        UniqueConstraint("store_id", "sku_id", "batch_no", "deleted_at", name="uk_store_sku_batch"),
        Index("idx_expire", "expire_at"),
        Index("idx_sku_store", "sku_id", "store_id"),
        # 索引: uk_store_sku_batch(store_id, sku_id, batch_no, deleted_at)
        #   用途: 门店×SKU×批次唯一锁定结存行,供 SELECT ... FOR UPDATE 行锁扣减。
        # 索引: idx_expire(expire_at) 用途: 临期预警扫描与 FIFO 出库排序。
        # 索引: idx_sku_store(sku_id, store_id) 用途: 按SKU横向看各门店/仓库存分布。
        {**MYSQL_TABLE_OPTIONS, "comment": "批次库存(结存表)"},
    )

    store_id: Mapped[int] = mapped_column(
        BIGINT_UNSIGNED, nullable=False, comment="0=总部仓,其余=门店ID"
    )
    sku_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    batch_no: Mapped[str] = mapped_column(String(32), nullable=False, comment="批次号,追溯主键")
    qty_base: Mapped[Decimal] = mapped_column(
        DECIMAL(14, 3), nullable=False, server_default=text("0"), comment="结存数量(基础单位)"
    )
    produced_at: Mapped[date | None] = mapped_column(Date, nullable=True, comment="生产日期")
    expire_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="保质期至")
    version: Mapped[int] = mapped_column(
        INT_UNSIGNED, nullable=False, default=0, server_default=text("0"), comment="乐观锁版本"
    )


class BatchFlow(Base, IdMixin, AuditMixin):
    """批次流水台账：每次批次变动一行（收货加/分拣减/报损减/盘点调整），仅追加、不软删。"""

    __tablename__ = "batch_flow"
    __table_args__ = (
        UniqueConstraint(
            "doc_type",
            "doc_no",
            "flow_type",
            "store_id",
            "sku_id",
            "batch_no",
            name="uk_flow_source",
        ),
        Index("idx_store_sku_batch", "store_id", "sku_id", "batch_no", "occurred_at"),
        Index("idx_doc", "doc_type", "doc_no"),
        Index("idx_operate", "operate_by", "occurred_at"),
        Index("idx_occurred", "occurred_at"),
        # 索引: uk_flow_source(doc_type, doc_no, flow_type, store_id, sku_id, batch_no)
        #   用途: 同一来源单据的同一行同一动作只能记一笔流水,防重复入账。
        # 索引: idx_store_sku_batch(store_id, sku_id, batch_no, occurred_at)
        #   用途: 按门店×SKU×批次拉时间序流水,批次追溯的主查询路径。
        # 索引: idx_doc(doc_type, doc_no) 用途: 由单据号反查其对库存的全部影响行,审计与对账常用。
        # 索引: idx_operate(operate_by, occurred_at) 用途: 按操作人审计其一段时间内的库存动作。
        # 索引: idx_occurred(occurred_at) 用途: 按时间窗统计进出量(日/周流水、对账期汇总)。
        {**MYSQL_TABLE_OPTIONS, "comment": "批次流水台账(收货/分拣/报损/盘点每次变动一行)"},
    )

    store_id: Mapped[int] = mapped_column(
        BIGINT_UNSIGNED, nullable=False, comment="0=总部仓,其余=门店ID"
    )
    sku_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    batch_no: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="批次号,与 batch_stock.batch_no 同源"
    )
    flow_type: Mapped[str] = mapped_column(
        Enum("receive_add", "pick_sub", "loss_sub", "count_adjust", name="enum_batch_flow_type"),
        nullable=False,
        comment="收货加/分拣减/报损减/盘点调整",
    )
    qty_change_base: Mapped[Decimal] = mapped_column(
        DECIMAL(14, 3), nullable=False, comment="变动量(基础单位):加为正、减为负"
    )
    qty_after_base: Mapped[Decimal] = mapped_column(
        DECIMAL(14, 3),
        nullable=False,
        comment="本次变动后结存(基础单位),与 batch_stock.qty_base 逐笔对账",
    )
    expire_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="变动时点的效期快照,避免后续改期影响历史还原"
    )
    doc_type: Mapped[str] = mapped_column(
        Enum(
            "purchase_order",
            "pick",
            "loss",
            "stock_count",
            "other",
            name="enum_batch_flow_doc_type",
        ),
        nullable=False,
        comment="关联单据类型",
    )
    doc_id: Mapped[int | None] = mapped_column(
        BIGINT_UNSIGNED, nullable=True, comment="关联单据头id(逻辑外键)"
    )
    doc_no: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="关联单据号,人可读的追溯入口"
    )
    doc_item_id: Mapped[int | None] = mapped_column(
        BIGINT_UNSIGNED, nullable=True, comment="关联单据明细id,定位到行"
    )
    operate_by: Mapped[int] = mapped_column(
        BIGINT_UNSIGNED, nullable=False, comment="操作人(逻辑外键→user.id)"
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="业务发生时间(非写入时间)"
    )
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
