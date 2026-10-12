"""接口测试：报损（TestClient + fake service，不连数据库）。

本地跑法（backend 目录下）：
    uv run pytest tests/test_loss.py -q
    # 或（本机 python 已装 fastapi/pydantic/pytest 时）：
    python -m pytest tests/test_loss.py -q

说明：SQLite 内存库与 MySQL 方言类型不兼容，故接口层用依赖注入替换 get_db /
get_current_user / get_loss_service，只断言路由装配、参数校验、数据范围（§8.1）
与统一响应结构，不连真实数据库；审批扣库存 + 写流水的库存在 service 层测。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.deps import PermissionCode
from app.main import app
from tests.fakes import FakeLossService, install_overrides, loss_row

LOSSES_URL = "/api/v1/losses"
ALL_PERMS = {
    PermissionCode.LOSS_CREATE,
    PermissionCode.LOSS_READ,
    PermissionCode.STOCK_ADJUST,
}


@pytest.fixture
def service() -> FakeLossService:
    return FakeLossService()


@pytest.fixture
def client(service: FakeLossService) -> Iterator[TestClient]:
    install_overrides(None, permissions=ALL_PERMS, loss=service)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ------------------------------------------------------------------- POST /losses
def test_create_loss_route(client: TestClient, service: FakeLossService) -> None:
    """门店提交报损：落 draft 单（不动库存），门店账号强制本店。"""
    resp = client.post(
        LOSSES_URL,
        json={
            "store_id": 3,
            "sku_id": 100,
            "batch_no": "B20261001",
            "qty_base": "2.000",
            "type": "expire",
            "reason": "临期",
        },
        headers={"Idempotency-Key": "loss-1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0 and body["message"] == "ok"
    data = body["data"]
    assert data["loss_no"] == "BS202610130001"
    assert data["store_id"] == 3
    assert data["status"] == "draft"
    assert data["type"] == "expire"
    assert data["qty_base"] == "2.000"
    _, kwargs = service.calls[-1]
    assert kwargs["payload"].sku_id == 100
    assert kwargs["operator_id"] == 7
    assert kwargs["idempotency_key"] == "loss-1"


def test_create_loss_store_account_defaults_to_own_store(
    client: TestClient, service: FakeLossService
) -> None:
    """门店账号可省略 store_id：resolve_store_id 取本店。"""
    install_overrides(None, permissions=ALL_PERMS, role="store_manager", store_id=3, loss=service)
    resp = client.post(LOSSES_URL, json={"sku_id": 100, "qty_base": "2.000", "type": "damage"})
    assert resp.status_code == 200
    assert resp.json()["data"]["store_id"] == 3
    _, kwargs = service.calls[-1]
    assert kwargs["actor"].store_id == 3


def test_create_loss_store_account_cross_store_is_40300(
    client: TestClient, service: FakeLossService
) -> None:
    """门店账号为他店提交报损：403 + 40300。"""
    install_overrides(None, permissions=ALL_PERMS, role="store_manager", store_id=3, loss=service)
    resp = client.post(
        LOSSES_URL,
        json={"store_id": 9, "sku_id": 100, "qty_base": "2.000", "type": "expire"},
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["code"] == 40300
    assert body["data"] is None


def test_create_loss_hq_without_store_id_is_400(
    client: TestClient, service: FakeLossService
) -> None:
    """总部账号未指定 store_id：service 抛 40000。"""
    resp = client.post(LOSSES_URL, json={"sku_id": 100, "qty_base": "2.000", "type": "expire"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_create_loss_rejects_bad_type(client: TestClient) -> None:
    """type 值域之外：400 + 40000。"""
    resp = client.post(
        LOSSES_URL,
        json={"store_id": 3, "sku_id": 100, "qty_base": "2.000", "type": "unknown"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_create_loss_rejects_non_positive_qty(client: TestClient) -> None:
    """qty_base 必须 >0：400 + 40000。"""
    resp = client.post(
        LOSSES_URL,
        json={"store_id": 3, "sku_id": 100, "qty_base": "0", "type": "expire"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_create_loss_requires_create_permission(
    client: TestClient, service: FakeLossService
) -> None:
    """缺少 loss:create（ops/admin 之外的账号）：403 + 40300，且不进入 service。"""
    install_overrides(None, permissions={PermissionCode.LOSS_READ}, loss=service)
    resp = client.post(
        LOSSES_URL, json={"store_id": 3, "sku_id": 100, "qty_base": "2.000", "type": "expire"}
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
    assert service.calls == []


# -------------------------------------------------------------------- GET /losses
def test_list_losses_shape_and_filters(client: TestClient, service: FakeLossService) -> None:
    """列表：store_id/status 透传，分页结构固定。"""
    service.losses = [
        loss_row(id=1, store_id=3, status="draft"),
        loss_row(id=2, store_id=3, status="approved"),
        loss_row(id=3, store_id=9, status="draft"),
    ]
    resp = client.get(
        LOSSES_URL, params={"page": 1, "page_size": 10, "store_id": 3, "status": "draft"}
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert set(data) == {"list", "total", "page", "page_size"}
    assert data["total"] == 1
    assert data["list"][0]["loss_no"] == "BS202610130001"
    _, kwargs = service.calls[-1]
    assert kwargs["store_id"] == 3
    assert kwargs["status"] == "draft"
    assert kwargs["page"] == 1 and kwargs["page_size"] == 10


def test_list_losses_store_account_injects_own_store(
    client: TestClient, service: FakeLossService
) -> None:
    """门店账号不传 store_id：resolve_list_store_scope 强制本店。"""
    install_overrides(
        None, permissions={PermissionCode.LOSS_READ}, role="store_manager", store_id=3, loss=service
    )
    service.losses = [loss_row(id=1, store_id=3), loss_row(id=2, store_id=9)]
    resp = client.get(LOSSES_URL)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert {row["store_id"] for row in data["list"]} == {3}
    _, kwargs = service.calls[-1]
    assert kwargs["store_id"] == 3


def test_list_losses_store_account_other_store_is_40300(
    client: TestClient, service: FakeLossService
) -> None:
    """门店账号显式查他店报损：403 + 40300。"""
    install_overrides(
        None, permissions={PermissionCode.LOSS_READ}, role="store_manager", store_id=3, loss=service
    )
    resp = client.get(LOSSES_URL, params={"store_id": 9})
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_list_losses_rejects_unknown_status(client: TestClient) -> None:
    """status 值域之外：400 + 40000。"""
    resp = client.get(LOSSES_URL, params={"status": "pending"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_list_losses_requires_read_permission(client: TestClient, service: FakeLossService) -> None:
    """缺少 loss:read：403 + 40300。"""
    install_overrides(None, permissions={PermissionCode.LOSS_CREATE}, loss=service)
    resp = client.get(LOSSES_URL)
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


# --------------------------------------------------------- POST /losses/{id}/approve
def test_approve_loss_route(client: TestClient, service: FakeLossService) -> None:
    """总部审批：draft→approved，落 approved_by/approved_at。"""
    resp = client.post(f"{LOSSES_URL}/5/approve")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["id"] == 5
    assert data["status"] == "approved"
    assert data["approved_by"] == 7
    assert data["approved_at"] is not None
    _, kwargs = service.calls[-1]
    assert kwargs["loss_id"] == 5
    assert kwargs["operator_id"] == 7


def test_approve_loss_requires_stock_adjust_permission(
    client: TestClient, service: FakeLossService
) -> None:
    """缺少 stock:adjust：403 + 40300，且不进入 service。"""
    install_overrides(None, permissions={PermissionCode.LOSS_READ}, loss=service)
    resp = client.post(f"{LOSSES_URL}/5/approve")
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
    assert service.calls == []


def test_approve_loss_rejects_zero_id(client: TestClient) -> None:
    """路径参数 loss_id 必须 ≥1：400 + 40000。"""
    resp = client.post(f"{LOSSES_URL}/0/approve")
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000
