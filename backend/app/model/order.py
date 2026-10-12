"""要货（§7.3）：要货单头 / 明细 / 智能体建议快照。

DDL 来源：docs/02-架构与模块设计.md v0.3.1 §7.3。
「智能体只建议、不落账」：建议快照落 agent_suggestion 只是留痕，须店长 confirm 才生效。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    DECIMAL,
    JSON,
    Date,
    DateTime,
    Enum,
    Index,
    String,
    UniqueConstraint,
    text,
)
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


class OrderHead(Base, IdMixin, AuditMixin, SoftDeleteMixin):
    """要货单头（门店→总部）。

    状态机 draft→confirmed→merged→cancelled；建议依据改由 agent_suggestion 承载。
    """

    __tablename__ = "order_head"
    __table_args__ = (
        UniqueConstraint("order_no", "deleted_at", name="uk_order_no"),
        UniqueConstraint("idempotency_key", "deleted_at", name="uk_idem"),
        Index("idx_store_require", "store_id", "require_date"),
        Index("idx_status_date", "status", "require_date"),
        Index("idx_agent_suggestion", "agent_suggestion_id"),
        # 索引: uk_order_no(order_no, deleted_at) 用途: 要货单号在未删除行内唯一。
        # 索引: uk_idem(idempotency_key, deleted_at) 用途: 幂等键防门店重复提交同一张单。
        # 索引: idx_store_require(store_id, require_date)
        #   用途: 门店查本店某日要货单、汇总任务按日扫描。
        # 索引: idx_status_date(status, require_date) 用途: 汇总任务取当日全部 confirmed 单。
        # 索引: idx_agent_suggestion(agent_suggestion_id)
        #   用途: 由建议反查其生成的单据,统计建议采纳率。
        {**MYSQL_TABLE_OPTIONS, "comment": "要货单头(门店→总部)"},
    )

    order_no: Mapped[str] = mapped_column(String(32), nullable=False)
    store_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    require_date: Mapped[date] = mapped_column(Date, nullable=False, comment="需求配送日")
    status: Mapped[str] = mapped_column(
        Enum("draft", "confirmed", "merged", "cancelled", name="enum_order_head_status"),
        nullable=False,
        server_default="draft",
    )
    source: Mapped[str] = mapped_column(
        Enum("manual", "agent", name="enum_order_head_source"),
        nullable=False,
        server_default="manual",
        comment="人工创建/智能体建议",
    )
    agent_suggestion_id: Mapped[int | None] = mapped_column(
        BIGINT_UNSIGNED,
        nullable=True,
        comment="采纳的智能体建议(逻辑外键→agent_suggestion.id),原 agent_advice JSON 已迁出",
    )
    confirm_by: Mapped[int | None] = mapped_column(
        BIGINT_UNSIGNED, nullable=True, comment="店长确认人"
    )
    confirm_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(
        INT_UNSIGNED, nullable=False, default=0, server_default=text("0")
    )


class OrderItem(Base, IdMixin, AuditMixin):
    """要货单明细。batch_no 为总部分拣后回填，把「要货→实际出库批次」串起来。"""

    __tablename__ = "order_item"
    __table_args__ = (
        Index("idx_order", "order_id"),
        Index("idx_sku", "sku_id"),
        # 索引: idx_order(order_id) 用途: 按要货单头取全部明细。
        # 索引: idx_sku(sku_id) 用途: 按SKU统计要货量,喂给销量分析与建议模型。
        {**MYSQL_TABLE_OPTIONS, "comment": "要货单明细"},
    )

    order_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    sku_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    qty_base: Mapped[Decimal] = mapped_column(DECIMAL(14, 3), nullable=False)
    qty_unit: Mapped[Decimal] = mapped_column(DECIMAL(14, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    batch_no: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="总部分拣后回填的批次号"
    )


class AgentSuggestion(Base, IdMixin, AuditMixin, SoftDeleteMixin):
    """智能体建议快照：可多轮生成、可被采纳/拒绝，payload 保存生成当时的依据快照。"""

    __tablename__ = "agent_suggestion"
    __table_args__ = (
        UniqueConstraint("idempotency_key", "deleted_at", name="uk_idem"),
        Index("idx_store_date_type", "store_id", "require_date", "suggestion_type"),
        Index("idx_order", "order_id"),
        Index("idx_status_created", "apply_status", "created_at"),
        # 索引: uk_idem(idempotency_key, deleted_at) 用途: 同一生成请求重试不产生重复建议快照。
        # 索引: idx_store_date_type(store_id, require_date, suggestion_type)
        #   用途: 门店/总部按日取某一类建议,端点 GET /agent/order-suggestions 的主路径。
        # 索引: idx_order(order_id) 用途: 由建议反查其生成的单据,校验"建议→确认"链路。
        # 索引: idx_status_created(apply_status, created_at)
        #   用途: 统计待处理/已采纳建议与采纳率,支撑治理看板。
        {**MYSQL_TABLE_OPTIONS, "comment": "智能体建议快照(由 order_head.agent_advice 迁入)"},
    )

    suggestion_type: Mapped[str] = mapped_column(
        Enum("order_suggest", "pick_plan", name="enum_agent_suggestion_type"),
        nullable=False,
        comment="要货建议/配货分拣计划建议",
    )
    store_id: Mapped[int] = mapped_column(
        BIGINT_UNSIGNED,
        nullable=False,
        server_default=text("0"),
        comment="建议对象门店,0=总部/全局(配货计划)",
    )
    require_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="需求配送日(配货计划可为空)"
    )
    payload: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        comment="建议明细与依据快照:销量/库存/效期/FIFO 预演结果 + 生成理由",
    )
    apply_status: Mapped[str] = mapped_column(
        Enum(
            "pending", "applied", "rejected", "expired", name="enum_agent_suggestion_apply_status"
        ),
        nullable=False,
        server_default="pending",
        comment="应用状态",
    )
    applied_by: Mapped[int | None] = mapped_column(
        BIGINT_UNSIGNED, nullable=True, comment="采纳人(店长/ops,逻辑外键→user.id)"
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="采纳时间")
    order_id: Mapped[int | None] = mapped_column(
        BIGINT_UNSIGNED, nullable=True, comment="apply 生成的 draft 要货单(逻辑外键→order_head.id)"
    )
    model: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="生成所用模型/提示词版本,便于回溯建议质量"
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="生成请求幂等键"
    )
    version: Mapped[int] = mapped_column(
        INT_UNSIGNED,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="乐观锁,防并发 apply",
    )
    # 覆写 Mixin 列：本表 DDL 对该列 COMMENT 为「生成时间」（其余表为无注释）。
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), comment="生成时间"
    )
