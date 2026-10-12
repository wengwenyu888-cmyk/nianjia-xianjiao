"""接口测试：主数据-SKU（TestClient + fake service，不连数据库）。

本地跑法（backend 目录下）：
    uv run pytest tests/test_skus.py -q
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.deps import PermissionCode
from app.main import app
from tests.fakes import FakeMasterService, install_overrides, sku_row


@pytest.fixture
def service() -> FakeMasterService:
    return FakeMasterService()


@pytest.fixture
def client(service: FakeMasterService) -> Iterator[TestClient]:
    install_overrides(service, permissions={PermissionCode.SKU_READ, PermissionCode.SKU_WRITE})
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_list_skus_shape_and_filters(client: TestClient, service: FakeMasterService) -> None:
    service.skus = [sku_row(id=1)]
    resp = client.get("/api/v1/skus", params={"category": "馅料-肉馅", "status": 1})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert set(data) == {"list", "total", "page", "page_size"}
    assert data["list"][0]["sku_no"] == "K001"
    _, kwargs = service.calls[-1]
    assert kwargs["category"] == "馅料-肉馅" and kwargs["status"] == 1


def test_create_sku_route(client: TestClient, service: FakeMasterService) -> None:
    body = {
        "sku_no": "K010",
        "name": "韭菜馅",
        "category": "馅料-蔬菜",
        "unit": "袋",
        "base_unit": "kg",
        "convert_factor": "5.0000",
        "shelf_life_hours": 48,
    }
    resp = client.post("/api/v1/skus", json=body)
    assert resp.status_code == 200
    assert resp.json()["code"] == 0
    assert resp.json()["data"]["sku_no"] == "K010"
    _, kwargs = service.calls[-1]
    assert kwargs["payload"].convert_factor == pytest.approx(5)
    assert kwargs["operator_id"] == 7


def test_create_sku_rejects_non_positive_convert_factor(client: TestClient) -> None:
    """换算因子必须 >0：按 docs/02 §8.1 统一为 400 + 40000。"""
    body = {
        "sku_no": "K011",
        "name": "坏换算",
        "category": "面皮",
        "unit": "袋",
        "base_unit": "kg",
        "convert_factor": "0",
        "shelf_life_hours": 24,
    }
    resp = client.post("/api/v1/skus", json=body)
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_create_sku_requires_permission(client: TestClient, service: FakeMasterService) -> None:
    install_overrides(service, permissions={PermissionCode.SKU_READ})
    resp = client.post(
        "/api/v1/skus",
        json={
            "sku_no": "K012",
            "name": "无权限",
            "category": "面皮",
            "unit": "袋",
            "base_unit": "kg",
            "shelf_life_hours": 24,
        },
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
