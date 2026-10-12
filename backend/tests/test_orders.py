"""接口测试：要货（TestClient + fake service，不连数据库）。

本地跑法（backend 目录下）：
    uv run pytest tests/test_orders.py -q
    # 或（本机 python 已装 fastapi/pydantic/pytest 时）：
    python -m pytest tests/test_orders.py -q

说明：SQLite 内存库与 MySQL 方言类型不兼容，故接口层用依赖注入替换 get_db /
get_current_user / get_order_service，只断言路由装配、参数校验、数据范围（§8.1）
与统一响应结构，不连真实数据库。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core.deps import PermissionCode
from app.main import app
from tests.fakes import FakeOrderService, install_overrides, order_item_row, order_row

ORDERS_URL = "/api/v1/orders"
READ_PERMS = {PermissionCode.ORDER_READ}
ALL_PERMS = {
    PermissionCode.ORDER_CREATE,
    PermissionCode.ORDER_UPDATE,
    PermissionCode.ORDER_CONFIRM,
    PermissionCode.ORDER_CANCEL,
    PermissionCode.ORDER_READ,
}
ITEM = {"sku_id": 100, "qty_unit": "2.000", "unit": "袋"}


@pytest.fixture
def service() -> FakeOrderService:
    return FakeOrderService()


@pytest.fixture
def client(service: FakeOrderService) -> Iterator[TestClient]:
    install_overrides(None, permissions=ALL_PERMS, order=service)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ------------------------------------------------------------------ POST /orders
def test_create_order_route_and_idempotency_header(
    client: TestClient, service: FakeOrderService
) -> None:
    """提交要货单：默认 draft 单，请求头幂等键与操作人透传给 service。"""
    resp = client.post(
        ORDERS_URL,
        json={"store_id": 3, "require_date": "2026-10-13", "items": [ITEM]},
        headers={"Idempotency-Key": "order-1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0 and body["message"] == "ok"
    data = body["data"]
    assert data["store_id"] == 3
    assert data["status"] == "draft"
    assert data["require_date"] == "2026-10-13"
    assert data["items"][0]["sku_id"] == 100
    _, kwargs = service.calls[-1]
    assert kwargs["idempotency_key"] == "order-1"
    assert kwargs["operator_id"] == 7
    assert kwargs["store_id_scope"] is None


def test_create_order_store_account_defaults_to_own_store(
    client: TestClient, service: FakeOrderService
) -> None:
    """门店账号可省略 store_id：取本人 store_id，并把数据范围传给 service。"""
    install_overrides(None, permissions=ALL_PERMS, role="store_manager", store_id=3, order=service)
    resp = client.post(ORDERS_URL, json={"require_date": "2026-10-13", "items": [ITEM]})
    assert resp.status_code == 200
    assert resp.json()["data"]["store_id"] == 3
    _, kwargs = service.calls[-1]
    assert kwargs["store_id_scope"] == 3


def test_create_order_rejects_empty_items(client: TestClient) -> None:
    """明细为空属参数校验：400 + 40000（错误码分段见 docs/02 §8.1）。"""
    resp = client.post(ORDERS_URL, json={"store_id": 3, "require_date": "2026-10-13", "items": []})
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 40000
    assert body["data"]


def test_create_order_rejects_duplicate_sku(client: TestClient) -> None:
    """同一 SKU 在一张要货单内只能一行：模型校验失败 → 400 + 40000。"""
    resp = client.post(
        ORDERS_URL,
        json={"store_id": 3, "require_date": "2026-10-13", "items": [ITEM, ITEM]},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_create_order_store_account_cross_store_is_40300(
    client: TestClient, service: FakeOrderService
) -> None:
    """门店账号为他店建单：service 抛 40300，接口层原样映射。"""
    install_overrides(None, permissions=ALL_PERMS, role="store_manager", store_id=3, order=service)
    resp = client.post(
        ORDERS_URL, json={"store_id": 9, "require_date": "2026-10-13", "items": [ITEM]}
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_create_order_requires_create_permission(
    client: TestClient, service: FakeOrderService
) -> None:
    """缺少 order:create：403 + 40300，且不进入 service。"""
    install_overrides(None, permissions=READ_PERMS, order=service)
    resp = client.post(
        ORDERS_URL, json={"store_id": 3, "require_date": "2026-10-13", "items": [ITEM]}
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
    assert service.calls == []


# --------------------------------------------------------------- PUT /orders/{id}
def test_update_order_route(client: TestClient, service: FakeOrderService) -> None:
    """修改草稿明细：items 传入即整单覆盖，version 透传乐观锁。"""
    resp = client.put(
        f"{ORDERS_URL}/9",
        json={"items": [ITEM], "version": 2},
        headers={"Idempotency-Key": "order-2"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == 9
    _, kwargs = service.calls[-1]
    assert kwargs["order_id"] == 9
    assert kwargs["payload"].version == 2
    assert kwargs["operator_id"] == 7


def test_update_order_rejects_empty_items(client: TestClient) -> None:
    """显式传空明细违反 min_length=1：400 + 40000。"""
    resp = client.put(f"{ORDERS_URL}/9", json={"items": []})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_update_order_requires_update_permission(
    client: TestClient, service: FakeOrderService
) -> None:
    """缺少 order:update：403 + 40300，且不进入 service。"""
    install_overrides(None, permissions=READ_PERMS, order=service)
    resp = client.put(f"{ORDERS_URL}/9", json={"items": [ITEM]})
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
    assert service.calls == []


# ------------------------------------------------------- confirm / cancel
def test_confirm_order_route(client: TestClient, service: FakeOrderService) -> None:
    """确认生效：draft→confirmed，落 confirm_by/confirm_at。"""
    resp = client.post(f"{ORDERS_URL}/9/confirm", headers={"Idempotency-Key": "order-3"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "confirmed"
    assert data["confirm_by"] == 7
    assert data["confirm_at"] is not None
    _, kwargs = service.calls[-1]
    assert kwargs["order_id"] == 9
    assert kwargs["operator_id"] == 7


def test_confirm_order_requires_confirm_permission(
    client: TestClient, service: FakeOrderService
) -> None:
    """缺少 order:confirm：403 + 40300。"""
    install_overrides(None, permissions=READ_PERMS, order=service)
    resp = client.post(f"{ORDERS_URL}/9/confirm")
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_confirm_order_rejects_undefined_id(client: TestClient) -> None:
    """路径参数 order_id 必须 ≥1：0 属参数校验 → 400 + 40000。"""
    resp = client.post(f"{ORDERS_URL}/0/confirm")
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_cancel_order_route(client: TestClient, service: FakeOrderService) -> None:
    """取消：仅 confirmed 前可取消，返回 cancelled 状态单。"""
    resp = client.post(f"{ORDERS_URL}/9/cancel", headers={"Idempotency-Key": "order-4"})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "cancelled"
    _, kwargs = service.calls[-1]
    assert kwargs["order_id"] == 9
    assert kwargs["operator_id"] == 7


def test_cancel_order_requires_cancel_permission(
    client: TestClient, service: FakeOrderService
) -> None:
    """缺少 order:cancel：403 + 40300。"""
    install_overrides(None, permissions=READ_PERMS, order=service)
    resp = client.post(f"{ORDERS_URL}/9/cancel")
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


# ------------------------------------------------------------------ GET /orders
def test_list_orders_shape_and_filters(client: TestClient, service: FakeOrderService) -> None:
    """分页查询：store_id / require_date / status 全部透传，响应为统一分页结构。"""
    service.orders = [
        order_row(id=1, store_id=3, require_date=date(2026, 10, 13), status="draft"),
        order_row(id=2, store_id=3, require_date=date(2026, 10, 14), status="confirmed"),
        order_row(id=3, store_id=9, require_date=date(2026, 10, 13), status="draft"),
    ]
    resp = client.get(
        ORDERS_URL,
        params={
            "page": 2,
            "page_size": 5,
            "store_id": 3,
            "require_date": "2026-10-13",
            "status": "draft",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert set(data) == {"list", "total", "page", "page_size"}
    assert data["total"] == 1
    assert data["page"] == 2 and data["page_size"] == 5
    assert data["list"][0]["order_no"] == "DD202610120001"
    assert data["list"][0]["items"][0]["sku_id"] == 100
    _, kwargs = service.calls[-1]
    assert kwargs["page"] == 2 and kwargs["page_size"] == 5
    assert kwargs["store_id"] == 3
    assert kwargs["require_date"] == date(2026, 10, 13)
    assert kwargs["status"] == "draft"
    assert kwargs["store_id_scope"] is None


def test_list_orders_store_account_injects_own_store(
    client: TestClient, service: FakeOrderService
) -> None:
    """门店账号不传 store_id：service 侧强制注入本店，列表只剩本店单。"""
    install_overrides(None, permissions=READ_PERMS, role="store_manager", store_id=3, order=service)
    service.orders = [order_row(id=1, store_id=3), order_row(id=2, store_id=9)]
    resp = client.get(ORDERS_URL)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert {row["store_id"] for row in data["list"]} == {3}
    _, kwargs = service.calls[-1]
    assert kwargs["store_id_scope"] == 3


def test_list_orders_store_account_other_store_is_40300(client: TestClient) -> None:
    """门店账号显式查他店：403 + 40300（数据范围铁律，§8.1）。"""
    install_overrides(None, permissions=READ_PERMS, role="store_manager", store_id=3)
    resp = client.get(ORDERS_URL, params={"store_id": 9})
    assert resp.status_code == 403
    body = resp.json()
    assert body["code"] == 40300
    assert body["data"] is None


def test_list_orders_rejects_page_size_over_200(client: TestClient) -> None:
    """page_size > 200 属参数校验：400 + 40000。"""
    resp = client.get(ORDERS_URL, params={"page_size": 201})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_list_orders_rejects_unknown_status(client: TestClient) -> None:
    """status 值域之外的取值：400 + 40000（Literal 校验）。"""
    resp = client.get(ORDERS_URL, params={"status": "unknown"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_list_orders_requires_read_permission(
    client: TestClient, service: FakeOrderService
) -> None:
    """缺少 order:read：403 + 40300。"""
    install_overrides(None, permissions=set(), order=service)
    resp = client.get(ORDERS_URL)
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_list_orders_detail_projection(client: TestClient, service: FakeOrderService) -> None:
    """明细投影：service 装配的 items 逐行进响应体（含分拣回填的 batch_no）。"""
    service.orders = [
        order_row(
            id=1,
            items=[
                order_item_row(id=11, sku_id=100),
                order_item_row(id=12, sku_id=101, batch_no="B20261001"),
            ],
        )
    ]
    data = client.get(ORDERS_URL).json()["data"]
    assert [row["sku_id"] for row in data["list"][0]["items"]] == [100, 101]
    assert data["list"][0]["items"][1]["batch_no"] == "B20261001"
