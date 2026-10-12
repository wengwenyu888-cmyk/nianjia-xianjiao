"""用户与权限（§7.6）：用户 / 角色 / 权限点 / 用户角色 / 角色权限点。

DDL 来源：docs/02-架构与模块设计.md v0.3.1 §7.6。
RBAC 三层正交：user_role 定"用户有哪些角色"，role_permission 定"角色有哪些权限点"
（网关按权限点判定 40300），user.store_id 定"数据范围"。
role / permission / user_role / role_permission 均不做软删除（停用走 status，撤销即删行）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, PrimaryKeyConstraint, String, UniqueConstraint, text
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


class User(Base, IdMixin, AuditMixin, SoftDeleteMixin):
    """用户。store_id 即数据范围：店长登录后所有查询强制注入本店条件，天然门店隔离。"""

    __tablename__ = "user"
    __table_args__ = (
        UniqueConstraint("username", "deleted_at", name="uk_username"),
        Index("idx_store", "store_id"),
        # 索引: uk_username(username, deleted_at)
        #   用途: 登录名在未删除行内唯一,禁用账号后同名可重新启用。
        # 索引: idx_store(store_id) 用途: 按门店列员工/按数据范围校验归属。
        {**MYSQL_TABLE_OPTIONS, "comment": "用户"},
    )

    username: Mapped[str] = mapped_column(String(32), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False, comment="bcrypt 哈希")
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    store_id: Mapped[int | None] = mapped_column(
        BIGINT_UNSIGNED, nullable=True, comment="NULL=总部用户;门店用户挂本店ID"
    )
    status: Mapped[int] = mapped_column(TINYINT, nullable=False, server_default=text("1"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Role(Base, IdMixin, AuditMixin):
    """角色（=权限点集合）。停用走 status，不做软删，故 uk_code 为单列。"""

    __tablename__ = "role"
    __table_args__ = (
        UniqueConstraint("code", name="uk_code"),
        # 索引: uk_code(code) 用途: 角色编码唯一,网关按 code 取权限点集合。
        {**MYSQL_TABLE_OPTIONS, "comment": "角色(=权限点集合)"},
    )

    code: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="admin/ops/driver/store_manager"
    )
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[int] = mapped_column(
        TINYINT, nullable=False, server_default=text("1"), comment="1启用 0停用"
    )


class Permission(Base, IdMixin, AuditMixin):
    """权限点。鉴权判定单元，由种子数据按 §8.3 初始化，代码只引用 code。"""

    __tablename__ = "permission"
    __table_args__ = (
        UniqueConstraint("code", name="uk_perm_code"),
        Index("idx_module", "module"),
        # 索引: uk_perm_code(code) 用途: 权限点编码全局唯一,鉴权时按 code 命中。
        # 索引: idx_module(module) 用途: 按模块分组展示权限点,供角色配置页使用。
        {**MYSQL_TABLE_OPTIONS, "comment": "权限点"},
    )

    code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="权限点编码,如 order:create / stock:adjust / agent:apply",
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="权限点名称")
    module: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="所属模块:master/purchase/order/agent/summary/delivery/loss/reconcile/report/system",
    )
    description: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="用途说明,与 §8.3 清单一致"
    )
    status: Mapped[int] = mapped_column(
        TINYINT, nullable=False, server_default=text("1"), comment="1启用 0停用"
    )


class UserRole(Base):
    """用户-角色。主键即唯一约束，同时支撑「按用户取角色」；撤销即删行。"""

    __tablename__ = "user_role"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "role_id"),
        # 索引: pk_user_role(user_id, role_id)
        #   用途: 主键即唯一约束,同时支撑"按用户取角色"的查询路径。
        {**MYSQL_TABLE_OPTIONS, "comment": "用户-角色"},
    )

    user_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    role_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)


class RolePermission(Base):
    """角色-权限点。

    注意：DDL 该表只有 created_by/created_at，无 updated_by/updated_at，故不用 AuditMixin。
    """

    __tablename__ = "role_permission"
    __table_args__ = (
        PrimaryKeyConstraint("role_id", "permission_id"),
        Index("idx_permission", "permission_id"),
        # 索引: idx_permission(permission_id) 用途: 反查"哪些角色拥有该权限点",用于变更影响面评估。
        {**MYSQL_TABLE_OPTIONS, "comment": "角色-权限点"},
    )

    role_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    permission_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    created_by: Mapped[int | None] = mapped_column(BIGINT_UNSIGNED, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
