"""purchase_order 增加 remark 备注列

背景：采购单备注是合理业务需求（如「紧急补货」「供应商换货」）。
初版 DDL 未含该列，服务层为避免「前端传了却被静默丢弃」而显式报错；
本次补列彻底解决，前后端契约自此一致。

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "purchase_order",
        sa.Column("remark", sa.String(length=255), nullable=True, comment="备注"),
    )


def downgrade() -> None:
    op.drop_column("purchase_order", "remark")
