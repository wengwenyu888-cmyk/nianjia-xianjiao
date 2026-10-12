"""Alembic 运行环境。

要点：
- 连接串从 app.core.config.settings 读取，不写死在 alembic.ini（镜像内不烘焙环境差异）；
- 先 import app.model，让 Base.metadata 收齐所有表，autogenerate 才能识别；
- 迁移只前进不回滚，downgrade 仅保留骨架。
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings

# 必须导入模型包，把全部表注册到 Base.metadata
import app.model  # noqa: F401
from app.model.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 运行时注入数据库连接串（含密码的串不落配置文件）
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL 不连库，用于人工审阅 DDL。"""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连库执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,  # 字段类型变更也生成迁移
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
