"""接口测试：主数据-供应商（TestClient + fake service，不连数据库）。

本地跑法（backend 目录下）：
    uv run pytest tests/test_suppliers.py -q
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.deps import PermissionCode
from app.main import app
from tests.fakes import FakeMasterService, install_overrides, supplier_row


@pytest.fixture
def service() -> FakeMasterService:
    return FakeMasterService()


@pytest.fixture
def client(service: FakeMasterService) -> Iterator[TestClient]:
    install_overrides(
        service,
        permissions={PermissionCode.SUPPLIER_READ, PermissionCode.SUPPLIER_WRITE},
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_list_suppliers_shape(client: TestClient, service: FakeMasterService) -> None:
    service.suppliers = [supplier_row(id=1)]
    resp = client.get("/api/v1/suppliers", params={"keyword": "食品"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert set(data) == {"list", "total", "page", "page_size"}
    assert data["list"][0]["supplier_no"] == "G001"
    _, kwargs = service.calls[-1]
    assert kwargs["keyword"] == "食品"


def test_create_supplier_route(client: TestClient, service: FakeMasterService) -> None:
    resp = client.post(
        "/api/v1/suppliers",
        json={"supplier_no": "G010", "name": "新供应商", "payment_terms": 45},
        headers={"Idempotency-Key": "sup-1"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["supplier_no"] == "G010"
    _, kwargs = service.calls[-1]
    assert kwargs["idempotency_key"] == "sup-1"
    assert kwargs["payload"].payment_terms == 45


def test_create_supplier_rejects_negative_payment_terms(client: TestClient) -> None:
    """账期为负属参数校验：按 docs/02 §8.1 统一为 400 + 40000。"""
    resp = client.post(
        "/api/v1/suppliers", json={"supplier_no": "G011", "name": "坏账期", "payment_terms": -1}
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_list_suppliers_requires_read_permission(
    client: TestClient, service: FakeMasterService
) -> None:
    install_overrides(service, permissions=set())
    resp = client.get("/api/v1/suppliers")
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
