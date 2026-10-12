"""汇总 v1 全部子路由。

新增业务模块只需在此 include_router 一行，main.py 不需要改动。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import health, prices, skus, stores, suppliers

api_router = APIRouter()

# 健康检查（无需鉴权）
api_router.include_router(health.router)

# 主数据（§8.2）：门店 / SKU / 供应商 / 价目
api_router.include_router(stores.router, prefix="/stores", tags=["主数据-门店"])
api_router.include_router(skus.router, prefix="/skus", tags=["主数据-SKU"])
api_router.include_router(suppliers.router, prefix="/suppliers", tags=["主数据-供应商"])
api_router.include_router(prices.router, prefix="/prices", tags=["主数据-价目"])

# 业务模块按落地顺序逐步接入（当前为骨架占位）：
# api_router.include_router(auth.router, prefix="/auth", tags=["认证"])
# api_router.include_router(orders.router, prefix="/orders", tags=["要货单"])
# api_router.include_router(summary.router, prefix="/summary", tags=["总部汇总"])
# api_router.include_router(picking.router, prefix="/picking", tags=["分拣单"])
# api_router.include_router(delivery.router, prefix="/delivery", tags=["配送单/司机任务"])
# api_router.include_router(receipt.router, prefix="/receipt", tags=["签收"])
# api_router.include_router(settlement.router, prefix="/settlement", tags=["对账"])
# api_router.include_router(agent.router, prefix="/agent", tags=["智能体建议"])
