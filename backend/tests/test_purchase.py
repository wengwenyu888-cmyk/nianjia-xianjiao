"""接口测试：采购（TestClient + fake service，不连数据库）。

本地跑法（backend 目录下）：
    uv run pytest tests/test_purchase.py -q
    # 或（本机 python 已装 fastapi/pydantic/pytest 时）：
    python -m pytest tests/test_purchase.py -q

说明：SQLite 内存库与 MySQL 方言类型不兼容，故接口层用依赖注入替换 get_db /
get_current_user / get_purchase_service，只断言路由装配、参数校验与统一响应结构，
不连真实数据库；收货写批次结存 + 流水的库存事务在 service 层测。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core.deps import PermissionCode
from app.main import app
from tests.fakes import (
    FakePurchaseService,
    install_overrides,
    purchase_item_row,
    purchase_order_row,
)

PO_URL = "/api/v1/purchase-orders"
ALL_PERMS = {
    PermissionCode.PURCHASE_CREATE,
    PermissionCode.PURCHASE_READ,
    PermissionCode.PURCHASE_RECEIVE,
}
PO_ITEM = {"sku_id": 100, "qty_unit": "2.000", "unit_price": "3.5000"}


@pytest.fixture
def service() -> FakePurchaseService:
    return FakePurchaseService()


@pytest.fixture
def client(service: FakePurchaseService) -> Iterator[TestClient]:
    install_overrides(None, permissions=ALL_PERMS, purchase=service)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ------------------------------------------------------------- POST /purchase-orders
def test_create_purchase_order_route(client: TestClient, service: FakePurchaseService) -> None:
    """建采购单：落 draft 单，明细金额由 qty_unit×unit_price 派生，幂等键透传。"""
    resp = client.post(
        PO_URL,
        json={"supplier_id": 5, "expected_date": "2026-10-14", "items": [PO_ITEM]},
        headers={"Idempotency-Key": "po-1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0 and body["message"] == "ok"
    data = body["data"]
    assert data["po_no"] == "CG202610130001"
    assert data["status"] == "draft"
    assert data["supplier_id"] == 5
    assert data["expected_date"] == "2026-10-14"
    assert data["total_amount"] == "7.00"
    assert data["items"][0]["unit_price"] == "3.5000"
    assert data["items"][0]["amount"] == "7.00"
    _, kwargs = service.calls[-1]
    assert kwargs["payload"].supplier_id == 5
    assert kwargs["payload"].expected_date == date(2026, 10, 14)
    assert kwargs["operator_id"] == 7
    assert kwargs["idempotency_key"] == "po-1"


def test_create_purchase_order_rejects_duplicate_sku(client: TestClient) -> None:
    """同一采购单内 SKU 重复：模型校验失败 → 400 + 40000。"""
    resp = client.post(PO_URL, json={"supplier_id": 5, "items": [PO_ITEM, PO_ITEM]})
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 40000
    assert body["data"]


def test_create_purchase_order_rejects_empty_items(client: TestClient) -> None:
    """明细至少 1 行（min_length=1）：400 + 40000。"""
    resp = client.post(PO_URL, json={"supplier_id": 5, "items": []})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_create_purchase_order_requires_create_permission(
    client: TestClient, service: FakePurchaseService
) -> None:
    """缺少 purchase:create：403 + 40300，且不进入 service。"""
    install_overrides(None, permissions={PermissionCode.PURCHASE_READ}, purchase=service)
    resp = client.post(PO_URL, json={"supplier_id": 5, "items": [PO_ITEM]})
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
    assert service.calls == []


# ---------------------------------------------------------------- GET /purchase-orders
def test_list_purchase_orders_shape_and_filters(
    client: TestClient, service: FakePurchaseService
) -> None:
    """列表：status/supplier_id 透传，分页结构固定。"""
    service.purchase_orders = [
        purchase_order_row(id=1, status="draft", supplier_id=5),
        purchase_order_row(id=2, status="received", supplier_id=6),
    ]
    resp = client.get(
        PO_URL, params={"page": 1, "page_size": 10, "status": "draft", "supplier_id": 5}
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert set(data) == {"list", "total", "page", "page_size"}
    assert data["total"] == 1
    assert data["list"][0]["supplier_name"] == "某食品厂"
    _, kwargs = service.calls[-1]
    assert kwargs["status"] == "draft"
    assert kwargs["supplier_id"] == 5
    assert kwargs["page"] == 1 and kwargs["page_size"] == 10


def test_list_purchase_orders_without_filters(
    client: TestClient, service: FakePurchaseService
) -> None:
    """不传过滤条件：service 收到 None，返回全部。"""
    service.purchase_orders = [purchase_order_row(id=1), purchase_order_row(id=2)]
    resp = client.get(PO_URL)
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 2
    _, kwargs = service.calls[-1]
    assert kwargs["status"] is None and kwargs["supplier_id"] is None


def test_list_purchase_orders_rejects_unknown_status(client: TestClient) -> None:
    """status 值域之外：400 + 40000。"""
    resp = client.get(PO_URL, params={"status": "unknown"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_list_purchase_orders_requires_read_permission(
    client: TestClient, service: FakePurchaseService
) -> None:
    """缺少 purchase:read：403 + 40300。"""
    install_overrides(None, permissions={PermissionCode.PURCHASE_CREATE}, purchase=service)
    resp = client.get(PO_URL)
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


# ---------------------------------------------------- POST /purchase-orders/{id}/receive
def test_receive_purchase_order_with_items(
    client: TestClient, service: FakePurchaseService
) -> None:
    """部分收货：明细按 sku 收货量提交，收货后状态仍可为 draft（余量可再收）。"""
    service.receive_order = purchase_order_row(
        id=1, status="draft", items=[purchase_item_row(received_qty_base="10.000")]
    )
    resp = client.post(
        f"{PO_URL}/1/receive",
        json={
            "batch_no_prefix": "CG20261013",
            "items": [{"sku_id": 100, "qty_base": "10.000", "expire_at": "2026-10-20T12:00:00"}],
        },
        headers={"Idempotency-Key": "rcv-1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["status"] == "draft"
    assert data["items"][0]["received_qty_base"] == "10.000"
    _, kwargs = service.calls[-1]
    assert kwargs["po_id"] == 1
    assert kwargs["payload"].batch_no_prefix == "CG20261013"
    assert kwargs["payload"].items[0].qty_base == 10
    assert kwargs["operator_id"] == 7
    assert kwargs["idempotency_key"] == "rcv-1"


def test_receive_purchase_order_without_body(
    client: TestClient, service: FakePurchaseService
) -> None:
    """省略 body：等价整单全量收货（service 收到 None），收货后状态 received。"""
    resp = client.post(f"{PO_URL}/2/receive")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "received"
    _, kwargs = service.calls[-1]
    assert kwargs["po_id"] == 2
    assert kwargs["payload"] is None


def test_receive_purchase_order_rejects_bad_expire_at(
    client: TestClient, service: FakePurchaseService
) -> None:
    """expire_at 非时间格式：400 + 40000。"""
    resp = client.post(f"{PO_URL}/1/receive", json={"expire_at": "not-a-datetime"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_receive_purchase_order_requires_receive_permission(
    client: TestClient, service: FakePurchaseService
) -> None:
    """缺少 purchase:receive：403 + 40300，且不进入 service。"""
    install_overrides(None, permissions={PermissionCode.PURCHASE_READ}, purchase=service)
    resp = client.post(f"{PO_URL}/1/receive")
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
    assert service.calls == []


def test_receive_purchase_order_rejects_zero_id(client: TestClient) -> None:
    """路径参数 po_id 必须 >0：400 + 40000。"""
    resp = client.post(f"{PO_URL}/0/receive")
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000
