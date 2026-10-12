"""结构化日志：统一格式 + 敏感字段脱敏。

约定：日志一律走 stdout，由容器运行环境采集（无状态约束，不写本地文件）。
"""

from __future__ import annotations

import logging
import re
import sys

from app.core.config import settings

# 需要脱敏的字段名（JSON 与 key=value 两种形态都会被替换）
SENSITIVE_KEYS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "api_key",
    "app_secret",
    "id_card",
    "phone",
    "mobile",
)

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

_CONFIGURED = False


def setup_logging(level: str | None = None) -> None:
    """初始化根 logger（幂等，多次调用只生效一次）。"""
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level or settings.LOG_LEVEL)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """取模块级 logger；首次调用顺带完成初始化。"""
    setup_logging()
    return logging.getLogger(name)


def mask_sensitive(text: str) -> str:
    """把日志文本中的敏感值替换为 ***（支持 JSON 与 key=value 两种形态）。"""
    if not text:
        return text
    pattern = re.compile(
        r"([\"']?(?:" + "|".join(SENSITIVE_KEYS) + r")[\"']?\s*[:=]\s*[\"']?)([^\"'&,\s}]+)",
        re.IGNORECASE,
    )
    return pattern.sub(r"\1***", text)


def mask_phone(value: str | None) -> str:
    """手机号脱敏：13812345678 → 138****5678。"""
    if not value or len(value) < 7:
        return value or ""
    return f"{value[:3]}****{value[-4:]}"
