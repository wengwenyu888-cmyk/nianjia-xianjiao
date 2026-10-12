"""接口测试：签收单（TestClient + fake service，不连数据库）。

本地跑法（backend 目录下）：
    uv run pytest tests/test_receipt.py -q
    # 或（本机 python 已装 fastapi/pydantic/pytest 时）：
    python -m pytest tests/test_receipt.py -q

说明：签收写入口是 POST /deliveries/{id}/sign（见 test_delivery.py），本文件只覆盖
GET /signs/{id}。接口层用依赖注入替换 get_db / get_current_user / get_receipt_service
（与配送同属 delivery_service），只断言路由装配、数据范围（§8.1）与统一响应结构。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.deps import PermissionCode
from app.main import app
from tests.fakes import (
    FakeDeliveryService,
    delivery_row,
    install_overrides,
    sign_row,
)

SIGNS_URL = "/api/v1/signs"
READ_PERMS = {PermissionCode.SIGN_READ}


@pytest.fixture
def service() -> FakeDeliveryService:
    return FakeDeliveryService()


@pytest.fixture
def client(service: FakeDeliveryService) -> Iterator[TestClient]:
    install_overrides(None, permissions=READ_PERMS, receipt=service)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_get_sign_route(client: TestClient, service: FakeDeliveryService) -> None:
    """签收单详情：明细含差异生成列，并带关联配送单号。"""
    resp = client.get(f"{SIGNS_URL}/1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0 and body["message"] == "ok"
    data = body["data"]
    assert data["id"] == 1
    assert data["delivery_id"] == 1
    assert data["delivery_no"] == "PS202610130001"
    assert data["store_id"] == 3
    assert data["status"] == "partial"
    item = data["items"][0]
    assert item["batch_no"] == "B20261001"
    assert item["send_qty_base"] == "10.000"
    assert item["sign_qty_base"] == "8.000"
    assert item["diff_qty_base"] == "2.000"
    _, kwargs = service.calls[-1]
    assert kwargs["sign_id"] == 1
    assert kwargs["actor"].user_id == 7


def test_get_sign_store_account_own_store_ok(
    client: TestClient, service: FakeDeliveryService
) -> None:
    """门店账号查看本店签收单：200，actor.store_id 与签收单门店一致。"""
    install_overrides(
        None, permissions=READ_PERMS, role="store_manager", store_id=3, receipt=service
    )
    resp = client.get(f"{SIGNS_URL}/1")
    assert resp.status_code == 200
    assert resp.json()["data"]["store_id"] == 3
    _, kwargs = service.calls[-1]
    assert kwargs["actor"].store_id == 3


def test_get_sign_store_account_other_store_is_40300(
    client: TestClient, service: FakeDeliveryService
) -> None:
    """门店账号查看他店签收单：403 + 40300。"""
    install_overrides(
        None, permissions=READ_PERMS, role="store_manager", store_id=9, receipt=service
    )
    resp = client.get(f"{SIGNS_URL}/1")
    assert resp.status_code == 403
    body = resp.json()
    assert body["code"] == 40300
    assert body["data"] is None


def test_get_sign_driver_other_task_is_40300(
    client: TestClient, service: FakeDeliveryService
) -> None:
    """纯司机查看他人配送任务的签收单：403 + 40300（driver_id 与本人不符）。"""
    install_overrides(None, permissions=READ_PERMS, role="driver", store_id=None, receipt=service)
    service.sign_row = sign_row(store_id=3)
    service.delivery = delivery_row(id=1, driver_id=10)  # 本人 user_id=7
    resp = client.get(f"{SIGNS_URL}/1")
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_get_sign_driver_own_task_ok(client: TestClient, service: FakeDeliveryService) -> None:
    """纯司机查看自己配送任务的签收单：200。"""
    install_overrides(None, permissions=READ_PERMS, role="driver", store_id=None, receipt=service)
    service.sign_row = sign_row(store_id=3)
    service.delivery = delivery_row(id=1, driver_id=7)  # 本人 user_id=7
    resp = client.get(f"{SIGNS_URL}/1")
    assert resp.status_code == 200
    assert resp.json()["data"]["delivery_no"] == "PS202610130001"


def test_get_sign_requires_sign_read_permission(
    client: TestClient, service: FakeDeliveryService
) -> None:
    """缺少 sign:read：403 + 40300。"""
    install_overrides(None, permissions=set(), receipt=service)
    resp = client.get(f"{SIGNS_URL}/1")
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_get_sign_rejects_zero_id(client: TestClient) -> None:
    """路径参数 sign_id 必须 ≥1：400 + 40000。"""
    resp = client.get(f"{SIGNS_URL}/0")
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000
