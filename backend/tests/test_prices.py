"""接口测试：主数据-价目（TestClient + fake service，不连数据库）。

本地跑法（backend 目录下）：
    uv run pytest tests/test_prices.py -q
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core.deps import PermissionCode
from app.main import app
from tests.fakes import FakeMasterService, install_overrides, price_row


@pytest.fixture
def service() -> FakeMasterService:
    return FakeMasterService()


@pytest.fixture
def client(service: FakeMasterService) -> Iterator[TestClient]:
    install_overrides(service, permissions={PermissionCode.PRICE_READ, PermissionCode.PRICE_WRITE})
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_create_price_route(client: TestClient, service: FakeMasterService) -> None:
    resp = client.post(
        "/api/v1/prices",
        json={
            "sku_id": 100,
            "price_type": "purchase",
            "price": "3.5000",
            "effective_from": "2026-01-01",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["code"] == 0
    assert resp.json()["data"]["sku_id"] == 100
    _, kwargs = service.calls[-1]
    assert kwargs["payload"].effective_from == date(2026, 1, 1)


def test_create_price_rejects_inverted_range(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/prices",
        json={
            "sku_id": 100,
            "price_type": "purchase",
            "price": "3.5",
            "effective_from": "2026-01-10",
            "effective_to": "2026-01-01",
        },
    )
    assert resp.status_code == 422


def test_list_prices_requires_sku_id(client: TestClient) -> None:
    resp = client.get("/api/v1/prices")
    assert resp.status_code == 422


def test_list_prices_passes_date_and_sku(client: TestClient, service: FakeMasterService) -> None:
    service.prices = [price_row(id=1)]
    resp = client.get("/api/v1/prices", params={"sku_id": 100, "date": "2026-03-01"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert set(data) == {"list", "total", "page", "page_size"}
    assert data["list"][0]["price_type"] == "purchase"
    _, kwargs = service.calls[-1]
    assert kwargs["sku_id"] == 100
    assert kwargs["on_date"] == date(2026, 3, 1)


def test_create_price_requires_write_permission(
    client: TestClient, service: FakeMasterService
) -> None:
    install_overrides(service, permissions={PermissionCode.PRICE_READ})
    resp = client.post(
        "/api/v1/prices",
        json={
            "sku_id": 100,
            "price_type": "purchase",
            "price": "3.5",
            "effective_from": "2026-01-01",
        },
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
