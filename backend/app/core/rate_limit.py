"""限流装配：slowapi 的 Limiter 集中在这里创建。

为什么单独一个模块：main.create_app 需要把 limiter 挂到 app.state，
业务路由（如登录）需要用它做端点级限流装饰器；两处必须是**同一个实例**，
否则装饰器的计数与 app.state 上的默认限流分属两套，阈值形同虚设。

未安装 slowapi 时 limiter=None，rate_limit 退化为透传装饰器：
应用仍可启动与装配路由，仅失去限流能力（与 main.py 原有降级行为一致）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

limiter: Any = None
try:  # pragma: no cover - 取决于依赖是否安装
    from slowapi import Limiter
    from slowapi.util import get_remote_address

    limiter = Limiter(key_func=get_remote_address, default_limits=[settings.RATE_LIMIT_DEFAULT])
except ModuleNotFoundError:  # pragma: no cover
    logger.warning("未安装 slowapi，接口限流已跳过")


def rate_limit(limit_value: str) -> Callable[[Any], Any]:
    """端点级限流装饰器；slowapi 缺失时返回透传装饰器（不阻断装配）。"""
    if limiter is None:

        def _passthrough(func: Any) -> Any:
            return func

        return _passthrough
    return limiter.limit(limit_value)
