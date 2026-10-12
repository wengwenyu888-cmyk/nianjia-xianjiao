"""接口测试：主数据-门店（TestClient + fake service，不连数据库）。

本地跑法（backend 目录下）：
    uv run pytest tests/test_stores.py -q

说明：SQLite 内存库与 MySQL 方言类型不兼容，故接口层用依赖注入替换 get_db /
get_current_user / get_master_service，只断言路由装配、参数校验与统一响应结构。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.deps import PermissionCode
from app.main import app
from tests.fakes import FakeMasterService, install_overrides, store_row


@pytest.fixture
def service() -> FakeMasterService:
    return FakeMasterService()


@pytest.fixture
def client(service: FakeMasterService) -> Iterator[TestClient]:
    install_overrides(
        service, permissions={PermissionCode.STORE_READ, PermissionCode.STORE_WRITE}
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_list_stores_shape_and_params(client: TestClient, service: FakeMasterService) -> None:
    service.stores = [store_row(id=1), store_row(id=2, store_no="S002")]
    resp = client.get("/api/v1/stores", params={"page": 2, "page_size": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0 and body["message"] == "ok"
    data = body["data"]
    assert set(data) == {"list", "total", "page", "page_size"}
    assert data["total"] == 2
    assert data["page"] == 2 and data["page_size"] == 5
    assert data["list"][0]["store_no"] == "S001"
    assert isinstance(data["list"][0]["version"], int)
    _, kwargs = service.calls[-1]
    assert kwargs["page"] == 2 and kwargs["page_size"] == 5


def test_list_stores_passes_keyword_and_store_scope(
    client: TestClient, service: FakeMasterService
) -> None:
    client.get("/api/v1/stores", params={"keyword": "S00", "status": 1})
    _, kwargs = service.calls[-1]
    assert kwargs["keyword"] == "S00" and kwargs["status"] == 1
    assert kwargs["store_id"] is None


def test_list_stores_rejects_page_size_over_200(client: TestClient) -> None:
    resp = client.get("/api/v1/stores", params={"page_size": 201})
    assert resp.status_code == 422
    assert resp.json()["code"] in {40000, 42200}


def test_create_store_route_and_idempotency_header(
    client: TestClient, service: FakeMasterService
) -> None:
    resp = client.post(
        "/api/v1/stores",
        json={"store_no": "S010", "name": "新店"},
        headers={"Idempotency-Key": "req-1"},
    )
    assert resp.status_code == 200
    assert resp.json()["code"] == 0
    assert resp.json()["data"]["store_no"] == "S010"
    _, kwargs = service.calls[-1]
    assert kwargs["idempotency_key"] == "req-1"
    assert kwargs["operator_id"] == 7


def test_create_store_validates_required_fields(client: TestClient) -> None:
    resp = client.post("/api/v1/stores", json={"store_no": "S010"})
    assert resp.status_code == 422
    assert resp.json()["code"] in {40000, 42200}
    assert resp.json()["data"]


def test_create_store_requires_write_permission(
    client: TestClient, service: FakeMasterService
) -> None:
    install_overrides(service, permissions={PermissionCode.STORE_READ})
    resp = client.post("/api/v1/stores", json={"store_no": "S011", "name": "无权限"})
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_list_stores_requires_read_permission(
    client: TestClient, service: FakeMasterService
) -> None:
    install_overrides(service, permissions=set())
    resp = client.get("/api/v1/stores")
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_update_store_route(client: TestClient, service: FakeMasterService) -> None:
    resp = client.put("/api/v1/stores/9", json={"delivery_cycle": "every_other_day"})
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == 9
    _, kwargs = service.calls[-1]
    assert kwargs["store_id"] == 9
    assert kwargs["payload"].delivery_cycle == "every_other_day"
    assert kwargs["operator_id"] == 7
