"""init_26_tables

Revision ID: 0001
Revises:
Create Date: 2026-10-12

来源：docs/02-架构与模块设计.md（v0.3.1）§7「数据表设计（DDL 草案）」——26 张表。
本文件为手写初始迁移：用 op.create_table 逐表创建，列名/类型/可空性/默认值/COMMENT/
唯一约束/普通索引与 §7 的 DDL 逐列一致（含 COMMENT 文案）。

§7 通用约定（已在本文件落地）：
- 引擎 InnoDB、utf8mb4、collate utf8mb4_0900_ai_ci；
- 审计四字段 created_by / created_at / updated_by / updated_at，表内逐表重复且内容一致；
- 软删除 deleted_at DATETIME NOT NULL DEFAULT '1970-01-01 00:00:00'
  （哨兵值=未删除；NOT NULL 是 (业务编码, deleted_at) 组合唯一索引真正生效的前提）；
- 幂等：idempotency_key VARCHAR(64) DEFAULT NULL + UNIQUE KEY uk_idem(idempotency_key, deleted_at)，
  签收单无软删，其 uk_idem 只含 idempotency_key；
- 数量 DECIMAL(14,3)、金额 DECIMAL(14,2)、单价 DECIMAL(12,4)；
- 不建物理外键（逻辑外键 + 服务层校验）。

实现说明：MySQL 上 SQLAlchemy 不把普通索引内联进 CREATE TABLE，而是紧随其后发
CREATE INDEX（索引名与列序不变，与 DDL 的 KEY idx_x (...) 等价）；唯一约束则内联为
CONSTRAINT uk_x UNIQUE (...)。索引对象仍写在 op.create_table 的参数里，与模型定义一一对应。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# --------------------------------------------------------------------------- #
# 公共类型 / 选项（与 app/model/base.py 完全一致）
# --------------------------------------------------------------------------- #
_BIGINT_U = mysql.BIGINT(unsigned=True)  # BIGINT UNSIGNED
_INT_U = mysql.INTEGER(unsigned=True)  # INT UNSIGNED
_TINYINT = mysql.TINYINT  # TINYINT
_DEC_14_3 = sa.DECIMAL(14, 3)  # 数量
_DEC_14_2 = sa.DECIMAL(14, 2)  # 金额
_DEC_12_4 = sa.DECIMAL(12, 4)  # 单价 / 换算系数
_DT = sa.DateTime()
_D = sa.Date()
_SENTINEL = sa.text("'1970-01-01 00:00:00'")
TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def _pk_id() -> sa.Column:
    """BIGINT UNSIGNED NOT NULL AUTO_INCREMENT 主键列（配合各表的 PrimaryKeyConstraint）。"""
    return sa.Column("id", _BIGINT_U, autoincrement=True, nullable=False)


def _audit(created_at_comment: str | None = None) -> list[sa.Column]:
    """审计四字段（§7 通用约定）。created_at_comment 仅供 agent_suggestion 使用。"""
    return [
        sa.Column("created_by", _BIGINT_U, nullable=True),
        sa.Column(
            "created_at",
            _DT,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment=created_at_comment,
        ),
        sa.Column("updated_by", _BIGINT_U, nullable=True),
        sa.Column(
            "updated_at",
            _DT,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
    ]


def _deleted_at() -> sa.Column:
    """软删除列（§7 通用约定）：NOT NULL + 1970-01-01 00:00:00 哨兵。"""
    return sa.Column(
        "deleted_at",
        _DT,
        nullable=False,
        server_default=_SENTINEL,
        comment="软删除时间,哨兵值=未删除",
    )


def upgrade() -> None:
    """建立 26 张表（顺序即依赖顺序：主数据 → 库存/采购 → 要货 → 汇总分拣 → 配送签收 → 报损对账 → 用户权限）。"""
    # ------------------------------------------------------------------ §7.1 主数据
    op.create_table(
        "store",
        _pk_id(),
        sa.Column("store_no", sa.String(32), nullable=False, comment="门店编码"),
        sa.Column("name", sa.String(64), nullable=False, comment="门店名称"),
        sa.Column("region", sa.String(64), nullable=True, comment="区域/城市"),
        sa.Column("address", sa.String(255), nullable=True),
        sa.Column("contact_name", sa.String(32), nullable=True),
        sa.Column("contact_phone", sa.String(32), nullable=True),
        sa.Column(
            "delivery_cycle",
            sa.Enum("daily", "every_other_day", name="enum_store_delivery_cycle"),
            nullable=False,
            server_default="daily",
            comment="配送节奏:日配/隔日配",
        ),
        sa.Column("status", _TINYINT, nullable=False, server_default=sa.text("1"), comment="1营业 0停业"),
        *_audit(),
        _deleted_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("store_no", "deleted_at", name="uk_store_no"),
        comment="门店",
        **TABLE_OPTIONS,
    )
    op.create_table(
        "supplier",
        _pk_id(),
        sa.Column("supplier_no", sa.String(32), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("contact_name", sa.String(32), nullable=True),
        sa.Column("contact_phone", sa.String(32), nullable=True),
        sa.Column("payment_terms", sa.Integer(), nullable=False, server_default=sa.text("0"), comment="账期(天)"),
        sa.Column("status", _TINYINT, nullable=False, server_default=sa.text("1")),
        *_audit(),
        _deleted_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("supplier_no", "deleted_at", name="uk_supplier_no"),
        comment="供应商",
        **TABLE_OPTIONS,
    )
    op.create_table(
        "sku",
        _pk_id(),
        sa.Column("sku_no", sa.String(32), nullable=False),
        sa.Column("name", sa.String(64), nullable=False, comment="品名"),
        sa.Column("category", sa.String(32), nullable=False, comment="馅料-肉馅/馅料-海鲜/面皮/调料/包材/鲜活"),
        sa.Column("spec", sa.String(64), nullable=True, comment="规格描述,如5kg/袋"),
        sa.Column("unit", sa.String(16), nullable=False, comment="订货/展示单位,如袋"),
        sa.Column("base_unit", sa.String(16), nullable=False, comment="基础计算单位,如kg"),
        sa.Column("convert_factor", _DEC_12_4, nullable=False, server_default=sa.text("1"), comment="1订货单位=多少基础单位"),
        sa.Column("shelf_life_hours", sa.Integer(), nullable=False, comment="保质期(小时)"),
        sa.Column(
            "supply_type",
            sa.Enum("direct", "temp", name="enum_sku_supply_type"),
            nullable=False,
            server_default="direct",
            comment="直配/临采",
        ),
        sa.Column("status", _TINYINT, nullable=False, server_default=sa.text("1")),
        *_audit(),
        _deleted_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sku_no", "deleted_at", name="uk_sku_no"),
        sa.Index("idx_category", "category"),
        comment="商品SKU",
        **TABLE_OPTIONS,
    )
    op.create_table(
        "price",
        _pk_id(),
        sa.Column("sku_id", _BIGINT_U, nullable=False, comment="逻辑外键→sku.id"),
        sa.Column(
            "price_type",
            sa.Enum("purchase", "transfer", name="enum_price_type"),
            nullable=False,
            comment="采购价/内部调拨价",
        ),
        sa.Column("price", _DEC_12_4, nullable=False, comment="单价(元/订货单位)"),
        sa.Column("effective_from", _D, nullable=False),
        sa.Column("effective_to", _D, nullable=True, comment="NULL=现行有效"),
        *_audit(),
        _deleted_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sku_id", "price_type", "effective_from", "deleted_at", name="uk_sku_type_from"),
        sa.Index("idx_sku_eff", "sku_id", "effective_from", "effective_to"),
        comment="价目表(含历史版本)",
        **TABLE_OPTIONS,
    )

    # ------------------------------------------------------------------ §7.2 库存与采购
    op.create_table(
        "batch_stock",
        _pk_id(),
        sa.Column("store_id", _BIGINT_U, nullable=False, comment="0=总部仓,其余=门店ID"),
        sa.Column("sku_id", _BIGINT_U, nullable=False),
        sa.Column("batch_no", sa.String(32), nullable=False, comment="批次号,追溯主键"),
        sa.Column("qty_base", _DEC_14_3, nullable=False, server_default=sa.text("0"), comment="结存数量(基础单位)"),
        sa.Column("produced_at", _D, nullable=True, comment="生产日期"),
        sa.Column("expire_at", _DT, nullable=False, comment="保质期至"),
        sa.Column("version", _INT_U, nullable=False, server_default=sa.text("0"), comment="乐观锁版本"),
        *_audit(),
        _deleted_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("store_id", "sku_id", "batch_no", "deleted_at", name="uk_store_sku_batch"),
        sa.Index("idx_expire", "expire_at"),
        sa.Index("idx_sku_store", "sku_id", "store_id"),
        comment="批次库存(结存表)",
        **TABLE_OPTIONS,
    )
    # batch_flow 仅追加（append-only）：无 deleted_at。
    op.create_table(
        "batch_flow",
        _pk_id(),
        sa.Column("store_id", _BIGINT_U, nullable=False, comment="0=总部仓,其余=门店ID"),
        sa.Column("sku_id", _BIGINT_U, nullable=False),
        sa.Column("batch_no", sa.String(32), nullable=False, comment="批次号,与 batch_stock.batch_no 同源"),
        sa.Column(
            "flow_type",
            sa.Enum("receive_add", "pick_sub", "loss_sub", "count_adjust", name="enum_batch_flow_type"),
            nullable=False,
            comment="收货加/分拣减/报损减/盘点调整",
        ),
        sa.Column("qty_change_base", _DEC_14_3, nullable=False, comment="变动量(基础单位):加为正、减为负"),
        sa.Column(
            "qty_after_base",
            _DEC_14_3,
            nullable=False,
            comment="本次变动后结存(基础单位),与 batch_stock.qty_base 逐笔对账",
        ),
        sa.Column(
            "expire_at",
            _DT,
            nullable=True,
            comment="变动时点的效期快照,避免后续改期影响历史还原",
        ),
        sa.Column(
            "doc_type",
            sa.Enum(
                "purchase_order",
                "pick",
                "loss",
                "stock_count",
                "other",
                name="enum_batch_flow_doc_type",
            ),
            nullable=False,
            comment="关联单据类型",
        ),
        sa.Column("doc_id", _BIGINT_U, nullable=True, comment="关联单据头id(逻辑外键)"),
        sa.Column("doc_no", sa.String(32), nullable=False, comment="关联单据号,人可读的追溯入口"),
        sa.Column("doc_item_id", _BIGINT_U, nullable=True, comment="关联单据明细id,定位到行"),
        sa.Column("operate_by", _BIGINT_U, nullable=False, comment="操作人(逻辑外键→user.id)"),
        sa.Column("occurred_at", _DT, nullable=False, comment="业务发生时间(非写入时间)"),
        sa.Column("remark", sa.String(255), nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "doc_type",
            "doc_no",
            "flow_type",
            "store_id",
            "sku_id",
            "batch_no",
            name="uk_flow_source",
        ),
        sa.Index("idx_store_sku_batch", "store_id", "sku_id", "batch_no", "occurred_at"),
        sa.Index("idx_doc", "doc_type", "doc_no"),
        sa.Index("idx_operate", "operate_by", "occurred_at"),
        sa.Index("idx_occurred", "occurred_at"),
        comment="批次流水台账(收货/分拣/报损/盘点每次变动一行)",
        **TABLE_OPTIONS,
    )
    op.create_table(
        "purchase_order",
        _pk_id(),
        sa.Column("po_no", sa.String(32), nullable=False),
        sa.Column("supplier_id", _BIGINT_U, nullable=False),
        sa.Column("store_id", _BIGINT_U, nullable=False, server_default=sa.text("0"), comment="收货点,0=总部仓"),
        sa.Column(
            "status",
            sa.Enum("draft", "submitted", "received", "cancelled", name="enum_purchase_order_status"),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("expect_at", _DT, nullable=True, comment="预计到货"),
        sa.Column("idempotency_key", sa.String(64), nullable=True, comment="幂等键"),
        sa.Column("version", _INT_U, nullable=False, server_default=sa.text("0")),
        *_audit(),
        _deleted_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("po_no", "deleted_at", name="uk_po_no"),
        sa.UniqueConstraint("idempotency_key", "deleted_at", name="uk_idem"),
        sa.Index("idx_supplier_status", "supplier_id", "status"),
        comment="采购单头",
        **TABLE_OPTIONS,
    )
    op.create_table(
        "purchase_order_item",
        _pk_id(),
        sa.Column("po_id", _BIGINT_U, nullable=False, comment="逻辑外键→purchase_order.id"),
        sa.Column("sku_id", _BIGINT_U, nullable=False),
        sa.Column("qty_base", _DEC_14_3, nullable=False),
        sa.Column("qty_unit", _DEC_14_3, nullable=False, comment="展示单位数量"),
        sa.Column("unit", sa.String(16), nullable=False),
        sa.Column("price", _DEC_12_4, nullable=False, comment="下单单价(元/展示单位)"),
        sa.Column("received_qty_base", _DEC_14_3, nullable=False, server_default=sa.text("0"), comment="已收数量(基础单位)"),
        *_audit(),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("idx_po", "po_id"),
        sa.Index("idx_sku", "sku_id"),
        comment="采购单明细",
        **TABLE_OPTIONS,
    )

    # ------------------------------------------------------------------ §7.3 要货与汇总
    op.create_table(
        "order_head",
        _pk_id(),
        sa.Column("order_no", sa.String(32), nullable=False),
        sa.Column("store_id", _BIGINT_U, nullable=False),
        sa.Column("require_date", _D, nullable=False, comment="需求配送日"),
        sa.Column(
            "status",
            sa.Enum("draft", "confirmed", "merged", "cancelled", name="enum_order_head_status"),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "source",
            sa.Enum("manual", "agent", name="enum_order_head_source"),
            nullable=False,
            server_default="manual",
            comment="人工创建/智能体建议",
        ),
        sa.Column(
            "agent_suggestion_id",
            _BIGINT_U,
            nullable=True,
            comment="采纳的智能体建议(逻辑外键→agent_suggestion.id),原 agent_advice JSON 已迁出",
        ),
        sa.Column("confirm_by", _BIGINT_U, nullable=True, comment="店长确认人"),
        sa.Column("confirm_at", _DT, nullable=True),
        sa.Column("idempotency_key", sa.String(64), nullable=True),
        sa.Column("version", _INT_U, nullable=False, server_default=sa.text("0")),
        *_audit(),
        _deleted_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_no", "deleted_at", name="uk_order_no"),
        sa.UniqueConstraint("idempotency_key", "deleted_at", name="uk_idem"),
        sa.Index("idx_store_require", "store_id", "require_date"),
        sa.Index("idx_status_date", "status", "require_date"),
        sa.Index("idx_agent_suggestion", "agent_suggestion_id"),
        comment="要货单头(门店→总部)",
        **TABLE_OPTIONS,
    )
    op.create_table(
        "order_item",
        _pk_id(),
        sa.Column("order_id", _BIGINT_U, nullable=False),
        sa.Column("sku_id", _BIGINT_U, nullable=False),
        sa.Column("qty_base", _DEC_14_3, nullable=False),
        sa.Column("qty_unit", _DEC_14_3, nullable=False),
        sa.Column("unit", sa.String(16), nullable=False),
        sa.Column("batch_no", sa.String(32), nullable=True, comment="总部分拣后回填的批次号"),
        *_audit(),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("idx_order", "order_id"),
        sa.Index("idx_sku", "sku_id"),
        comment="要货单明细",
        **TABLE_OPTIONS,
    )
    op.create_table(
        "agent_suggestion",
        _pk_id(),
        sa.Column(
            "suggestion_type",
            sa.Enum("order_suggest", "pick_plan", name="enum_agent_suggestion_type"),
            nullable=False,
            comment="要货建议/配货分拣计划建议",
        ),
        sa.Column(
            "store_id",
            _BIGINT_U,
            nullable=False,
            server_default=sa.text("0"),
            comment="建议对象门店,0=总部/全局(配货计划)",
        ),
        sa.Column("require_date", _D, nullable=True, comment="需求配送日(配货计划可为空)"),
        sa.Column(
            "payload",
            sa.JSON(),
            nullable=False,
            comment="建议明细与依据快照:销量/库存/效期/FIFO 预演结果 + 生成理由",
        ),
        sa.Column(
            "apply_status",
            sa.Enum("pending", "applied", "rejected", "expired", name="enum_agent_suggestion_apply_status"),
            nullable=False,
            server_default="pending",
            comment="应用状态",
        ),
        sa.Column("applied_by", _BIGINT_U, nullable=True, comment="采纳人(店长/ops,逻辑外键→user.id)"),
        sa.Column("applied_at", _DT, nullable=True, comment="采纳时间"),
        sa.Column(
            "order_id",
            _BIGINT_U,
            nullable=True,
            comment="apply 生成的 draft 要货单(逻辑外键→order_head.id)",
        ),
        sa.Column(
            "model",
            sa.String(64),
            nullable=True,
            comment="生成所用模型/提示词版本,便于回溯建议质量",
        ),
        sa.Column("idempotency_key", sa.String(64), nullable=True, comment="生成请求幂等键"),
        sa.Column(
            "version",
            _INT_U,
            nullable=False,
            server_default=sa.text("0"),
            comment="乐观锁,防并发 apply",
        ),
        *_audit(created_at_comment="生成时间"),
        _deleted_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", "deleted_at", name="uk_idem"),
        sa.Index("idx_store_date_type", "store_id", "require_date", "suggestion_type"),
        sa.Index("idx_order", "order_id"),
        sa.Index("idx_status_created", "apply_status", "created_at"),
        comment="智能体建议快照(由 order_head.agent_advice 迁入)",
        **TABLE_OPTIONS,
    )
    op.create_table(
        "summary",
        _pk_id(),
        sa.Column("summary_no", sa.String(32), nullable=False),
        sa.Column("require_date", _D, nullable=False),
        sa.Column(
            "status",
            sa.Enum("generated", "picking", "picked", "delivering", "done", name="enum_summary_status"),
            nullable=False,
            server_default="generated",
        ),
        sa.Column("line_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("idempotency_key", sa.String(64), nullable=True, comment="生成请求幂等键"),
        *_audit(),
        _deleted_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("summary_no", "deleted_at", name="uk_summary_no"),
        sa.UniqueConstraint("require_date", "deleted_at", name="uk_req_date"),
        sa.UniqueConstraint("idempotency_key", "deleted_at", name="uk_idem"),
        sa.Index("idx_status", "status"),
        comment="汇总单(每配送日一张)",
        **TABLE_OPTIONS,
    )
    op.create_table(
        "summary_item",
        _pk_id(),
        sa.Column("summary_id", _BIGINT_U, nullable=False),
        sa.Column("sku_id", _BIGINT_U, nullable=False),
        sa.Column(
            "total_qty_base",
            _DEC_14_3,
            nullable=False,
            comment="该SKU当日要货总量(基础单位)",
        ),
        *_audit(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("summary_id", "sku_id", name="uk_summary_sku"),
        comment="汇总单明细(SKU×总量)",
        **TABLE_OPTIONS,
    )

    # ------------------------------------------------------------------ §7.4 分拣、配送与签收
    op.create_table(
        "pick",
        _pk_id(),
        sa.Column("pick_no", sa.String(32), nullable=False),
        sa.Column("summary_id", _BIGINT_U, nullable=False),
        sa.Column("store_id", _BIGINT_U, nullable=False, comment="拣货目标门店"),
        sa.Column(
            "status",
            sa.Enum("created", "picking", "done", "cancelled", name="enum_pick_status"),
            nullable=False,
            server_default="created",
        ),
        sa.Column("idempotency_key", sa.String(64), nullable=True, comment="生成请求幂等键"),
        sa.Column("version", _INT_U, nullable=False, server_default=sa.text("0")),
        *_audit(),
        _deleted_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pick_no", "deleted_at", name="uk_pick_no"),
        sa.UniqueConstraint("idempotency_key", "deleted_at", name="uk_idem"),
        sa.Index("idx_summary_store", "summary_id", "store_id"),
        comment="分拣单(按门店)",
        **TABLE_OPTIONS,
    )
    op.create_table(
        "pick_item",
        _pk_id(),
        sa.Column("pick_id", _BIGINT_U, nullable=False),
        sa.Column("sku_id", _BIGINT_U, nullable=False),
        sa.Column("batch_no", sa.String(32), nullable=False, comment="实际拣出的批次号"),
        sa.Column("qty_base", _DEC_14_3, nullable=False, comment="拣出数量(基础单位)"),
        *_audit(),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("idx_pick", "pick_id"),
        sa.Index("idx_sku_batch", "sku_id", "batch_no"),
        comment="分拣明细(批次在此落定)",
        **TABLE_OPTIONS,
    )
    op.create_table(
        "delivery",
        _pk_id(),
        sa.Column("delivery_no", sa.String(32), nullable=False),
        sa.Column("summary_id", _BIGINT_U, nullable=False),
        sa.Column("store_id", _BIGINT_U, nullable=False),
        sa.Column("require_date", _D, nullable=False),
        sa.Column("driver_id", _BIGINT_U, nullable=True, comment="司机(逻辑外键→user.id)"),
        sa.Column("plate_no", sa.String(16), nullable=True),
        sa.Column(
            "status",
            sa.Enum("loaded", "on_way", "signed", "partial", "rejected", name="enum_delivery_status"),
            nullable=False,
            server_default="loaded",
        ),
        sa.Column("loaded_at", _DT, nullable=True),
        sa.Column("signed_at", _DT, nullable=True),
        sa.Column("idempotency_key", sa.String(64), nullable=True, comment="生成请求幂等键"),
        *_audit(),
        _deleted_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delivery_no", "deleted_at", name="uk_delivery_no"),
        sa.UniqueConstraint("idempotency_key", "deleted_at", name="uk_idem"),
        sa.Index("idx_driver_date", "driver_id", "require_date"),
        sa.Index("idx_summary", "summary_id"),
        comment="配送单(一车一店一单)",
        **TABLE_OPTIONS,
    )
    op.create_table(
        "delivery_item",
        _pk_id(),
        sa.Column("delivery_id", _BIGINT_U, nullable=False),
        sa.Column("pick_item_id", _BIGINT_U, nullable=True, comment="来源分拣明细"),
        sa.Column("sku_id", _BIGINT_U, nullable=False),
        sa.Column("batch_no", sa.String(32), nullable=False),
        sa.Column("qty_base", _DEC_14_3, nullable=False, comment="发送数量(基础单位)"),
        *_audit(),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("idx_delivery", "delivery_id"),
        sa.Index("idx_pick_item", "pick_item_id"),
        comment="配送明细",
        **TABLE_OPTIONS,
    )
    # sign 不做软删除：无 deleted_at，uk_idem 只含 idempotency_key。
    op.create_table(
        "sign",
        _pk_id(),
        sa.Column("delivery_id", _BIGINT_U, nullable=False),
        sa.Column("store_id", _BIGINT_U, nullable=False),
        sa.Column("sign_by", _BIGINT_U, nullable=False, comment="签收人(店长/店员)"),
        sa.Column("sign_at", _DT, nullable=False),
        sa.Column(
            "status",
            sa.Enum("full", "partial", "reject", name="enum_sign_status"),
            nullable=False,
            server_default="full",
        ),
        sa.Column("remark", sa.String(255), nullable=True),
        sa.Column("idempotency_key", sa.String(64), nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delivery_id", name="uk_delivery"),
        sa.UniqueConstraint("idempotency_key", name="uk_idem"),
        comment="签收单(电子POD)",
        **TABLE_OPTIONS,
    )
    op.create_table(
        "sign_item",
        _pk_id(),
        sa.Column("sign_id", _BIGINT_U, nullable=False),
        sa.Column("sku_id", _BIGINT_U, nullable=False),
        sa.Column("batch_no", sa.String(32), nullable=False),
        sa.Column("send_qty_base", _DEC_14_3, nullable=False, comment="应送数量(基础单位)"),
        sa.Column("sign_qty_base", _DEC_14_3, nullable=False, comment="实收数量(基础单位)"),
        sa.Column(
            "diff_qty_base",
            _DEC_14_3,
            sa.Computed("send_qty_base - sign_qty_base", persisted=True),
            nullable=True,
            comment="差异=应送-实收",
        ),
        *_audit(),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("idx_sign", "sign_id"),
        comment="签收明细",
        **TABLE_OPTIONS,
    )

    # ------------------------------------------------------------------ §7.5 报损与对账
    op.create_table(
        "loss",
        _pk_id(),
        sa.Column("loss_no", sa.String(32), nullable=False),
        sa.Column("store_id", _BIGINT_U, nullable=False),
        sa.Column("sku_id", _BIGINT_U, nullable=False),
        sa.Column("batch_no", sa.String(32), nullable=True),
        sa.Column("qty_base", _DEC_14_3, nullable=False),
        sa.Column(
            "type",
            sa.Enum("expire", "damage", "count_diff", name="enum_loss_type"),
            nullable=False,
            comment="临期报损/破损/盘点差异",
        ),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column(
            "status",
            sa.Enum("draft", "approved", name="enum_loss_status"),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("approved_by", _BIGINT_U, nullable=True),
        sa.Column("approved_at", _DT, nullable=True),
        sa.Column("idempotency_key", sa.String(64), nullable=True, comment="提交请求幂等键"),
        *_audit(),
        _deleted_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("loss_no", "deleted_at", name="uk_loss_no"),
        sa.UniqueConstraint("idempotency_key", "deleted_at", name="uk_idem"),
        sa.Index("idx_store_sku", "store_id", "sku_id"),
        sa.Index("idx_store_created", "store_id", "created_at"),
        comment="报损单",
        **TABLE_OPTIONS,
    )
    op.create_table(
        "reconcile",
        _pk_id(),
        sa.Column("period", sa.String(16), nullable=False, comment="对账周期,如2026-W42"),
        sa.Column("store_id", _BIGINT_U, nullable=False),
        sa.Column(
            "total_amount",
            _DEC_14_2,
            nullable=False,
            server_default=sa.text("0"),
            comment="本周期内部结算额(元)",
        ),
        sa.Column(
            "diff_amount",
            _DEC_14_2,
            nullable=False,
            server_default=sa.text("0"),
            comment="与外部台账(管家婆)差异额",
        ),
        sa.Column(
            "status",
            sa.Enum("draft", "confirmed", "done", name="enum_reconcile_status"),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("confirmed_by", _BIGINT_U, nullable=True),
        sa.Column("confirmed_at", _DT, nullable=True),
        sa.Column("idempotency_key", sa.String(64), nullable=True, comment="生成请求幂等键"),
        *_audit(),
        _deleted_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("store_id", "period", "deleted_at", name="uk_store_period"),
        sa.UniqueConstraint("idempotency_key", "deleted_at", name="uk_idem"),
        comment="对账单(门店×周期)",
        **TABLE_OPTIONS,
    )

    # ------------------------------------------------------------------ §7.6 用户与权限
    op.create_table(
        "user",
        _pk_id(),
        sa.Column("username", sa.String(32), nullable=False),
        sa.Column("password_hash", sa.String(128), nullable=False, comment="bcrypt 哈希"),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("store_id", _BIGINT_U, nullable=True, comment="NULL=总部用户;门店用户挂本店ID"),
        sa.Column("status", _TINYINT, nullable=False, server_default=sa.text("1")),
        sa.Column("last_login_at", _DT, nullable=True),
        *_audit(),
        _deleted_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", "deleted_at", name="uk_username"),
        sa.Index("idx_store", "store_id"),
        comment="用户",
        **TABLE_OPTIONS,
    )
    op.create_table(
        "role",
        _pk_id(),
        sa.Column("code", sa.String(32), nullable=False, comment="admin/ops/driver/store_manager"),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("status", _TINYINT, nullable=False, server_default=sa.text("1"), comment="1启用 0停用"),
        *_audit(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uk_code"),
        comment="角色(=权限点集合)",
        **TABLE_OPTIONS,
    )
    op.create_table(
        "permission",
        _pk_id(),
        sa.Column(
            "code",
            sa.String(64),
            nullable=False,
            comment="权限点编码,如 order:create / stock:adjust / agent:apply",
        ),
        sa.Column("name", sa.String(64), nullable=False, comment="权限点名称"),
        sa.Column(
            "module",
            sa.String(32),
            nullable=False,
            comment="所属模块:master/purchase/order/agent/summary/delivery/loss/reconcile/report/system",
        ),
        sa.Column("description", sa.String(255), nullable=True, comment="用途说明,与 §8.3 清单一致"),
        sa.Column("status", _TINYINT, nullable=False, server_default=sa.text("1"), comment="1启用 0停用"),
        *_audit(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uk_perm_code"),
        sa.Index("idx_module", "module"),
        comment="权限点",
        **TABLE_OPTIONS,
    )
    op.create_table(
        "role_permission",
        sa.Column("role_id", _BIGINT_U, nullable=False),
        sa.Column("permission_id", _BIGINT_U, nullable=False),
        sa.Column("created_by", _BIGINT_U, nullable=True),
        sa.Column("created_at", _DT, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("role_id", "permission_id"),
        sa.Index("idx_permission", "permission_id"),
        comment="角色-权限点",
        **TABLE_OPTIONS,
    )
    op.create_table(
        "user_role",
        sa.Column("user_id", _BIGINT_U, nullable=False),
        sa.Column("role_id", _BIGINT_U, nullable=False),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
        comment="用户-角色",
        **TABLE_OPTIONS,
    )


def downgrade() -> None:
    """逆序删表（仅保留骨架：迁移只前进不回滚，见 alembic/env.py 说明）。"""
    for table_name in (
        "user_role",
        "role_permission",
        "permission",
        "role",
        "user",
        "reconcile",
        "loss",
        "sign_item",
        "sign",
        "delivery_item",
        "delivery",
        "pick_item",
        "pick",
        "summary_item",
        "summary",
        "agent_suggestion",
        "order_item",
        "order_head",
        "purchase_order_item",
        "purchase_order",
        "batch_flow",
        "batch_stock",
        "price",
        "sku",
        "supplier",
        "store",
    ):
        op.drop_table(table_name)
