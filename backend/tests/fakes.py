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
from typing import Annotated, Any

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core.deps import (
    bearer_scheme,
    get_auth_service,
    get_current_user,
    get_db,
    get_master_service,
)
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


class FakeAuthService:
    """假认证服务：不连库、不依赖 jose / passlib，只验证 api 层的 40100 分支。

    passwords：口令正确的用户；deleted_users：模拟已软删/停用的用户（口令对也拒绝）。
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.passwords: dict[str, str] = {"zhangsan": "St0re#2026"}
        self.deleted_users: set[str] = {"lisi"}
        self.token = "fake-jwt-token"
        self.profile: dict[str, Any] = {
            "id": 7,
            "username": "zhangsan",
            "display_name": "张三",
            "store_id": 3,
            "role_codes": ["store_manager"],
            "permission_codes": ["master:store:read", "order:create"],
        }

    def authenticate(self, db: Any, username: str, password: str) -> dict[str, Any] | None:
        """镜像真实服务语义：不存在 / 软删 / 口令错误一律 None。"""
        self.calls.append((username, password))
        if username in self.deleted_users:
            return None
        expected = self.passwords.get(username)
        if expected is None or password != expected:
            return None
        return {"token": self.token, "token_type": "bearer", "user": dict(self.profile)}


def install_auth_overrides(
    auth_service: Any,
    *,
    profile: dict[str, Any] | None = None,
) -> None:
    """认证接口测试替身：替换 auth service，并让 get_current_user 真实校验 Bearer。

    与 install_overrides 的差别：这里不直接返回固定用户，而是先检查 Authorization 头，
    这样「/auth/me 必须带 Bearer」才有可断言的 40100（不解析 JWT，故无需 jose）。
    """
    current = profile or {
        "user_id": 7,
        "username": "zhangsan",
        "name": "张三",
        "role": "store",
        "roles": ["store_manager"],
        "store_id": 3,
        "permissions": ["master:store:read"],
    }

    def fake_current_user(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    ) -> dict[str, Any]:
        if credentials is None or not credentials.credentials:
            raise HTTPException(
                status_code=401,
                detail="未登录或缺少访问令牌",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return current

    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_current_user] = fake_current_user
