"""SQLAlchemy Base 与公共字段 Mixin（表结构的唯一事实源）。

约定：
- 模型一律继承 Base + 需要的 Mixin；模型里不写业务方法（业务在 service 层）。
- 公共字段只在 Mixin 里定义一次，表模型不重复声明（唯一例外见 `order.py` 的
  AgentSuggestion.created_at：该表 COMMENT 与 Mixin 不同，故在表模型内覆写）。
- 字段类型 / 默认值 / 注释严格对齐 docs/02-架构与模块设计.md（v0.3.1）§7「通用约定」：
  主键与外键 BIGINT UNSIGNED、乐观锁 version INT UNSIGNED、数量 DECIMAL(14,3)、
  软删除 deleted_at DATETIME NOT NULL DEFAULT '1970-01-01 00:00:00'、
  时间戳 DEFAULT CURRENT_TIMESTAMP（updated_at 追加 ON UPDATE CURRENT_TIMESTAMP）。
- 所有表模型必须显式写 __tablename__：DDL 表名不是类名的蛇形复数（如 OrderHead -> order_head）。
"""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import DateTime, func, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

# --------------------------------------------------------------------------- #
# 类型别名：与 §7 DDL 逐字对应
# --------------------------------------------------------------------------- #
BIGINT_UNSIGNED = mysql.BIGINT(unsigned=True)  # BIGINT UNSIGNED（主键/外键/操作人）
INT_UNSIGNED = mysql.INTEGER(unsigned=True)  # INT UNSIGNED（乐观锁 version）
TINYINT = mysql.TINYINT  # TINYINT（status 等小状态位）

# 建表公共选项：ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
MYSQL_TABLE_OPTIONS: dict = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}

# 软删除哨兵值：deleted_at 等于该值表示「未删除」，其余值 = 删除时间。
# 必须是 NOT NULL 哨兵而不是 NULL：MySQL 唯一索引中 NULL 互不相等、不参与约束，
# 若用 DEFAULT NULL，(store_no, deleted_at) 上所有未删除行都不受约束，唯一性形同虚设
# （见 §7 通用约定「软删除坑」）。ORM 侧默认值也用它，保证应用层写入不产生 NULL。
SOFT_DELETE_SENTINEL = datetime(1970, 1, 1, 0, 0, 0)


class Base(DeclarativeBase):
    """全项目唯一的声明式基类。"""

    @declared_attr.directive
    def __tablename__(cls) -> str:  # noqa: N805
        """表名默认取类名的蛇形复数：OrderItem -> order_items。

        注意：本项目 DDL 表名并非该规则（order_head / summary / sign ...），
        因此每个模型都必须显式声明 __tablename__。
        """
        name = re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower()
        return name if name.endswith("s") else f"{name}s"

    def to_dict(self) -> dict:
        """调试用浅转换；对外输出一律用 pydantic schema，禁止直接返回 ORM 对象。"""
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class IdMixin:
    """自增主键：BIGINT UNSIGNED NOT NULL AUTO_INCREMENT。"""

    id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, primary_key=True, autoincrement=True)


class TimestampMixin:
    """审计时间字段：默认值与「更新即刷新」都由数据库维护。

    updated_at 的 ON UPDATE 写在 server_default 里是 SQLAlchemy 对 MySQL 的既定写法
    （server_onupdate 不参与 DDL 渲染），与 DDL 的
    `DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` 完全一致。
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        onupdate=func.now(),
    )


class AuditMixin(TimestampMixin):
    """审计增强：记录操作人，对账纠纷时可追溯（见安全要点「审计留痕」）。"""

    created_by: Mapped[int | None] = mapped_column(BIGINT_UNSIGNED, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(BIGINT_UNSIGNED, nullable=True)


class SoftDeleteMixin:
    """软删除（§7 通用约定）：deleted_at NOT NULL，哨兵值=未删除，其余值=删除时间。

    单据类数据物理删除会破坏对账链路；组合唯一索引（业务编码 + deleted_at）也依赖
    该哨兵值才真正生效，软删后同一编码可重新启用且历史行留档。
    """

    deleted_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=SOFT_DELETE_SENTINEL,
        server_default=text("'1970-01-01 00:00:00'"),
        comment="软删除时间,哨兵值=未删除",
    )


class VersionMixin:
    """乐观锁版本号：并发改单（如分拣数量）防覆盖。

    本批 26 张表的 version 列 COMMENT 各不相同（如 agent_suggestion 为
    '乐观锁,防并发 apply'），为与 DDL 逐列一致，表模型内显式声明该列；
    本 Mixin 与 DDL 语义保持一致，供后续新表直接复用。
    """

    version: Mapped[int] = mapped_column(
        INT_UNSIGNED, nullable=False, default=0, server_default=text("0"), comment="乐观锁版本"
    )
