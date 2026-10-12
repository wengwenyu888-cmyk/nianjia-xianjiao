"""汇总 v1 全部子路由。

新增业务模块只需在此 include_router 一行，main.py 不需要改动。

路由分组（严格按 §8.2 的路径与方法）：
- 认证 /auth、主数据 /stores /skus /suppliers /prices
- 要货 /orders、智能体 /agent、汇总分拣 /summaries /picks
- 配送签收 / 报损 / 对账由并行开发产出：按约定文件名惰性注册，
  文件未就绪（ImportError）时只记日志、不注册，保证应用始终可启动。
"""

from __future__ import annotations

import importlib

from fastapi import APIRouter

from app.api.v1 import (
    agent,
    auth,
    health,
    orders,
    picking,
    prices,
    skus,
    stores,
    summary,
    suppliers,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

api_router = APIRouter()

# 健康检查（无需鉴权）
api_router.include_router(health.router)

# 认证（§8.2）：登录签发 JWT / 当前用户与权限点
api_router.include_router(auth.router, prefix="/auth", tags=["认证"])

# 主数据（§8.2）：门店 / SKU / 供应商 / 价目
api_router.include_router(stores.router, prefix="/stores", tags=["主数据-门店"])
api_router.include_router(skus.router, prefix="/skus", tags=["主数据-SKU"])
api_router.include_router(suppliers.router, prefix="/suppliers", tags=["主数据-供应商"])
api_router.include_router(prices.router, prefix="/prices", tags=["主数据-价目"])

# 要货（§8.2）：POST /orders、PUT /orders/{id}、POST /orders/{id}/confirm|cancel、GET /orders
api_router.include_router(orders.router, prefix="/orders", tags=["要货"])

# 智能体（§8.2）：POST /agent/order-suggestions、GET .../{id}、apply、POST /agent/pick-plan
api_router.include_router(agent.router, prefix="/agent", tags=["智能体建议"])

# 汇总分拣（§8.2）：POST /summaries/generate、GET /summaries、POST /picks、POST /picks/{id}/complete
api_router.include_router(summary.router, prefix="/summaries", tags=["汇总"])
api_router.include_router(picking.router, prefix="/picks", tags=["分拣"])


def _include_optional(module_name: str, *, prefix: str, probe: str, tags: list[str]) -> None:
    """惰性注册并行开发中的模块（delivery / receipt / loss / settlement）。

    - 文件未就绪（ImportError）或未暴露 router → 记日志跳过，应用仍可启动；
    - prefix 自适应：若模块内路由已写成 §8.2 全路径（如 /deliveries），
      则不再叠加 prefix，避免出现 /deliveries/deliveries。
    """
    try:
        module = importlib.import_module(f"app.api.v1.{module_name}")
        module_router = module.router
    except ImportError as exc:
        logger.warning("路由模块 app.api.v1.%s 尚未就绪，暂不注册：%s", module_name, exc)
        return
    except AttributeError as exc:
        logger.warning("路由模块 app.api.v1.%s 未暴露 router，暂不注册：%s", module_name, exc)
        return

    paths = [route.path for route in module_router.routes]
    effective_prefix = "" if any(path.startswith(probe) for path in paths) else prefix
    api_router.include_router(module_router, prefix=effective_prefix, tags=tags)
    logger.info("已注册路由模块 app.api.v1.%s（prefix=%r）", module_name, effective_prefix)


# 配送签收（§8.2）：/deliveries 装车/发车/签收 + /signs/{id} 签收单详情
_include_optional("delivery", prefix="/deliveries", probe="/deliveries", tags=["配送签收"])
_include_optional("receipt", prefix="/signs", probe="/signs", tags=["配送签收-签收"])
# 报损（§8.2）：POST /losses、GET /losses、POST /losses/{id}/approve
_include_optional("loss", prefix="/losses", probe="/losses", tags=["报损"])
# 对账核算（§8.2）：POST /reconciles/generate、GET /reconciles、POST /reconciles/{id}/confirm
_include_optional("settlement", prefix="/reconciles", probe="/reconciles", tags=["对账核算"])


def _include_optional_extra(
    module_name: str, attr: str, *, prefix: str, tags: list[str]
) -> None:
    """注册模块内额外暴露的 router（如 settlement.stores_router）。

    背景：_include_optional 只取 module.router；而 settlement 为覆盖 /stores 前缀
    另暴露 stores_router（GET /stores/{id}/profit、/kpi），不单独注册会缺这 2 个端点。
    """
    try:
        module = importlib.import_module(f"app.api.v1.{module_name}")
        extra_router = getattr(module, attr)
    except (ImportError, AttributeError) as exc:
        logger.warning("路由模块 app.api.v1.%s.%s 尚未就绪，暂不注册：%s", module_name, attr, exc)
        return
    api_router.include_router(extra_router, prefix=prefix, tags=tags)
    logger.info("已注册路由模块 app.api.v1.%s.%s（prefix=%r）", module_name, attr, prefix)


# 门店报表（§8.2）：GET /stores/{id}/profit、GET /stores/{id}/kpi
_include_optional_extra(
    "settlement", "stores_router", prefix="/stores", tags=["对账核算-门店报表"]
)
