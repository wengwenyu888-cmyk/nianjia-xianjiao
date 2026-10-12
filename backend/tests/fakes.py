"""接口层测试替身（SQLite 内存库与 MySQL 方言类型不兼容，故不连库）。

本地跑法（backend 目录下）：
    uv run pytest

- fake service：接口层只断言路由装配、参数传递与统一响应结构；
- row_* 构造器：造出带 updated_at 的 ORM 风格对象，供 XxxOut.model_validate 使用。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from app.core.deps import get_current_user, get_db, get_master_service
from app.main import app
from app.service.store_service import PageResult

_NOW = datetime(2026, 10, 12, 10, 0, 0)


def store_row(**overrides: Any) -> SimpleNamespace:
    """门店 ORM 风格对象。"""
    base: dict[str, Any] = {
        "id": 1,
        "store_no": "S001",
        "name": "示例门店",
        "region": "上海",
        "address": "某路 1 号",
        "contact_name": "店长",
        "contact_phone": "13800000000",
        "delivery_cycle": "daily",
        "status": 1,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def sku_row(**overrides: Any) -> SimpleNamespace:
    """SKU ORM 风格对象。"""
    base: dict[str, Any] = {
        "id": 1,
        "sku_no": "K001",
        "name": "猪肉馅",
        "category": "馅料-肉馅",
        "spec": "5kg/袋",
        "unit": "袋",
        "base_unit": "kg",
        "convert_factor": Decimal("5.0000"),
        "shelf_life_hours": 72,
        "supply_type": "direct",
        "status": 1,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def supplier_row(**overrides: Any) -> SimpleNamespace:
    """供应商 ORM 风格对象。"""
    base: dict[str, Any] = {
        "id": 1,
        "supplier_no": "G001",
        "name": "某食品厂",
        "contact_name": "业务员",
        "contact_phone": "13900000000",
        "payment_terms": 30,
        "status": 1,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def price_row(**overrides: Any) -> SimpleNamespace:
    """价目 ORM 风格对象。"""
    base: dict[str, Any] = {
        "id": 1,
        "sku_id": 100,
        "price_type": "purchase",
        "price": Decimal("3.5000"),
        "effective_from": date(2026, 1, 1),
        "effective_to": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class FakeMasterService:
    """记录调用的假服务：接口层验证路由与参数，不触碰数据库。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.stores: list[Any] = []
        self.skus: list[Any] = []
        self.suppliers: list[Any] = []
        self.prices: list[Any] = []

    # ---- 门店
    def list_stores(self, db: Any, **kwargs: Any) -> PageResult[Any]:
        self.calls.append(("list_stores", kwargs))
        return PageResult(items=self.stores, total=len(self.stores))

    def create_store(self, db: Any, payload: Any, **kwargs: Any) -> Any:
        self.calls.append(("create_store", {"payload": payload, **kwargs}))
        return store_row(id=1, **payload.model_dump())

    def update_store(self, db: Any, store_id: int, payload: Any, **kwargs: Any) -> Any:
        self.calls.append(("update_store", {"store_id": store_id, "payload": payload, **kwargs}))
        return store_row(id=store_id, **payload.model_dump(exclude_unset=True, exclude={"version"}))

    # ---- SKU
    def list_skus(self, db: Any, **kwargs: Any) -> PageResult[Any]:
        self.calls.append(("list_skus", kwargs))
        return PageResult(items=self.skus, total=len(self.skus))

    def create_sku(self, db: Any, payload: Any, **kwargs: Any) -> Any:
        self.calls.append(("create_sku", {"payload": payload, **kwargs}))
        return sku_row(id=1, **payload.model_dump())

    # ---- 供应商
    def list_suppliers(self, db: Any, **kwargs: Any) -> PageResult[Any]:
        self.calls.append(("list_suppliers", kwargs))
        return PageResult(items=self.suppliers, total=len(self.suppliers))

    def create_supplier(self, db: Any, payload: Any, **kwargs: Any) -> Any:
        self.calls.append(("create_supplier", {"payload": payload, **kwargs}))
        return supplier_row(id=1, **payload.model_dump())

    # ---- 价目
    def list_prices(self, db: Any, **kwargs: Any) -> PageResult[Any]:
        self.calls.append(("list_prices", kwargs))
        return PageResult(items=self.prices, total=len(self.prices))

    def create_price(self, db: Any, payload: Any, **kwargs: Any) -> Any:
        self.calls.append(("create_price", {"payload": payload, **kwargs}))
        return price_row(id=1, **payload.model_dump())


def install_overrides(
    service: Any,
    *,
    permissions: Iterable[Any] = (),
    role: str = "admin",
    store_id: int | None = None,
) -> None:
    """把 get_db / get_current_user / get_master_service 全部替换为测试替身。"""
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_master_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": 7,
        "username": "tester",
        "name": "测试用户",
        "role": role,
        "roles": [role],
        "store_id": store_id,
        "permissions": [str(code) for code in permissions],
    }
