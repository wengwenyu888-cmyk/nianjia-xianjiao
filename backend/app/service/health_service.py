"""健康检查：数据库连通性探测（骨架阶段唯一的最小服务）。"""

from __future__ import annotations

from sqlalchemy import text

from app.core.deps import SessionLocal
from app.core.logging import get_logger

logger = get_logger(__name__)


def check_database() -> bool:
    """执行 SELECT 1 探测数据库；连不上返回 False 而不抛异常（探针不应 500）。"""
    session = SessionLocal()
    try:
        session.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - 探针需要吞掉一切连接异常
        logger.warning("数据库连通性探测失败：%s", exc)
        return False
    finally:
        session.close()
