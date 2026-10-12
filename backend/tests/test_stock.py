"""接口测试：库存（TestClient + fake service，不连数据库）。

本地跑法（backend 目录下）：
    uv run pytest tests/test_stock.py -q
    # 或（本机 python 已装 fastapi/pydantic/pytest 时）：
    python -m pytest tests/test_stock.py -q

说明：SQLite 内存库与 MySQL 方言类型不兼容，故接口层用依赖注入替换 get_db /
get_current_user / get_stock_service，只断言路由装配、筛选参数透传、临期阈值默认值
与统一响应结构，不连真实数据库。本组三个端点均为只读（不接收 Idempotency-Key）。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.deps import PermissionCode
from app.main import app
from tests.fakes import (
    FakeStockService,
    install_overrides,
    stock_alert_item,
    stock_alerts_result,
    stock_flow_out_row,
    stock_out_row,
)

STOCKS_URL = "/api/v1/stocks"
ALERTS_URL = "/api/v1/stocks/alerts"
FLOWS_URL = "/api/v1/stock-flows"
READ_PERMS = {PermissionCode.STOCK_READ}


@pytest.fixture
def service() -> FakeStockService:
    return FakeStockService()


@pytest.fixture
def client(service: FakeStockService) -> Iterator[TestClient]:
    install_overrides(None, permissions=READ_PERMS, stock=service)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --------------------------------------------------------------------- GET /stocks
def test_list_stocks_shape_and_filters(client: TestClient, service: FakeStockService) -> None:
    """批次库存分页：store_id/sku_id/batch_no 透传，行含临期投影字段。"""
    service.stocks = [stock_out_row(id=71)]
    resp = client.get(
        STOCKS_URL,
        params={"page": 2, "page_size": 5, "store_id": 0, "sku_id": 100, "batch_no": "B20261001"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0 and body["message"] == "ok"
    data = body["data"]
    assert set(data) == {"list", "total", "page", "page_size"}
    assert data["total"] == 1
    assert data["page"] == 2 and data["page_size"] == 5
    row = data["list"][0]
    assert row["store_id"] == 0
    assert row["store_name"] == "总部仓"
    assert row["batch_no"] == "B20261001"
    assert row["qty_base"] == "10.000"
    assert row["hours_to_expire"] == "192.00"
    assert row["expiring"] is False
    _, kwargs = service.calls[-1]
    assert kwargs["store_id"] == 0
    assert kwargs["sku_id"] == 100
    assert kwargs["batch_no"] == "B20261001"
    assert kwargs["page"] == 2 and kwargs["page_size"] == 5


def test_list_stocks_expire_within_hours_filter(
    client: TestClient, service: FakeStockService
) -> None:
    """临期筛选：expire_within_hours 透传，同时作为 expiring 阈值。"""
    service.stocks = [stock_out_row(expiring=True, hours_to_expire="12.00")]
    resp = client.get(STOCKS_URL, params={"expire_within_hours": 48})
    assert resp.status_code == 200
    assert resp.json()["data"]["list"][0]["expiring"] is True
    _, kwargs = service.calls[-1]
    assert kwargs["expire_within_hours"] == 48


def test_list_stocks_defaults(client: TestClient, service: FakeStockService) -> None:
    """缺省口径：只返回有货批次（include_zero=False），临期筛选为 None，门店不限。"""
    resp = client.get(STOCKS_URL)
    assert resp.status_code == 200
    _, kwargs = service.calls[-1]
    assert kwargs["store_id"] is None
    assert kwargs["expire_within_hours"] is None
    assert kwargs["include_zero"] is False


def test_list_stocks_include_zero(client: TestClient, service: FakeStockService) -> None:
    """include_zero=true：连同零/负结存批次一并返回。"""
    service.stocks = [
        stock_out_row(id=71, qty_base="10.000"),
        stock_out_row(id=72, qty_base="0.000", batch_no="B20260901"),
    ]
    resp = client.get(STOCKS_URL, params={"include_zero": True})
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 2
    _, kwargs = service.calls[-1]
    assert kwargs["include_zero"] is True


def test_list_stocks_rejects_expire_hours_out_of_range(client: TestClient) -> None:
    """expire_within_hours 上限 8760（1 年）：超限 400 + 40000。"""
    resp = client.get(STOCKS_URL, params={"expire_within_hours": 8761})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_list_stocks_rejects_zero_expire_hours(client: TestClient) -> None:
    """expire_within_hours 必须 ≥1：0 属参数校验 → 400 + 40000。"""
    resp = client.get(STOCKS_URL, params={"expire_within_hours": 0})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_list_stocks_rejects_too_long_batch_no(client: TestClient) -> None:
    """batch_no 超过 32 字符：400 + 40000。"""
    resp = client.get(STOCKS_URL, params={"batch_no": "B" * 33})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_list_stocks_requires_read_permission(
    client: TestClient, service: FakeStockService
) -> None:
    """缺少 stock:read：403 + 40300，且不进入 service。"""
    install_overrides(None, permissions=set(), stock=service)
    resp = client.get(STOCKS_URL)
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
    assert service.calls == []


# --------------------------------------------------------------- GET /stocks/alerts
def test_stock_alerts_shape(client: TestClient, service: FakeStockService) -> None:
    """预警汇总：临期清单 + 低库存清单 + 口径 summary（无分页）。"""
    resp = client.get(ALERTS_URL)
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert set(data) == {"expiring", "low_stock", "summary"}
    assert data["expiring"][0]["expiring"] is True
    assert data["low_stock"][0]["sku_id"] == 100
    assert data["low_stock"][0]["threshold"] == "20.000"
    summary = data["summary"]
    assert summary["expiring_count"] == 1
    assert summary["low_stock_count"] == 1
    assert summary["expire_hours"] == 24
    assert summary["low_qty_base"] == "20.000"
    _, kwargs = service.calls[-1]
    assert kwargs["store_id"] is None
    assert kwargs["expire_hours"] == 24
    assert str(kwargs["low_qty_base"]) == "20.000"
    assert kwargs["limit"] == 50


def test_stock_alerts_custom_thresholds(client: TestClient, service: FakeStockService) -> None:
    """自定义阈值与门店范围逐项透传（0=总部仓）。"""
    service.alerts = stock_alerts_result(
        expiring=[],
        low_stock=[stock_alert_item(qty_base="3.000", threshold="10.000")],
        expiring_count=0,
        low_stock_count=1,
        expire_hours=12,
        low_qty_base="10.000",
    )
    resp = client.get(
        ALERTS_URL,
        params={"store_id": 0, "expire_hours": 12, "low_qty_base": "10.000", "limit": 20},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["summary"]["low_stock_count"] == 1
    _, kwargs = service.calls[-1]
    assert kwargs["store_id"] == 0
    assert kwargs["expire_hours"] == 12
    assert kwargs["limit"] == 20


def test_stock_alerts_negative_threshold_is_validation_error(client: TestClient) -> None:
    """low_qty_base 不允许负数（ge=0）：400 + 40000。"""
    resp = client.get(ALERTS_URL, params={"low_qty_base": "-1"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_stock_alerts_limit_over_max_is_validation_error(client: TestClient) -> None:
    """limit 上限 200：超限 400 + 40000。"""
    resp = client.get(ALERTS_URL, params={"limit": 201})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_stock_alerts_requires_read_permission(
    client: TestClient, service: FakeStockService
) -> None:
    """缺少 stock:read：403 + 40300。"""
    install_overrides(None, permissions=set(), stock=service)
    resp = client.get(ALERTS_URL)
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


# -------------------------------------------------------------- GET /stock-flows
def test_list_stock_flows_shape_and_filters(client: TestClient, service: FakeStockService) -> None:
    """流水查询：store_id/sku_id/batch_no/flow_type 透传，行含追溯字段。"""
    service.flows = [stock_flow_out_row()]
    resp = client.get(
        FLOWS_URL,
        params={
            "page": 1,
            "page_size": 20,
            "store_id": 0,
            "sku_id": 100,
            "batch_no": "B20261001",
            "flow_type": "receive_add",
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert set(data) == {"list", "total", "page", "page_size"}
    assert data["total"] == 1
    row = data["list"][0]
    assert row["flow_type"] == "receive_add"
    assert row["qty_change_base"] == "10.000"
    assert row["qty_after_base"] == "10.000"
    assert row["doc_type"] == "purchase_order"
    assert row["doc_no"] == "CG202610130001"
    _, kwargs = service.calls[-1]
    assert kwargs["store_id"] == 0
    assert kwargs["sku_id"] == 100
    assert kwargs["batch_no"] == "B20261001"
    assert kwargs["flow_type"] == "receive_add"


def test_list_stock_flows_without_filters(client: TestClient, service: FakeStockService) -> None:
    """不传过滤条件：service 收到全 None（全量流水）。"""
    service.flows = [stock_flow_out_row(id=81), stock_flow_out_row(id=82, flow_type="pick_sub")]
    resp = client.get(FLOWS_URL)
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 2
    _, kwargs = service.calls[-1]
    assert kwargs["store_id"] is None and kwargs["flow_type"] is None


def test_list_stock_flows_rejects_unknown_flow_type(client: TestClient) -> None:
    """flow_type 值域之外：400 + 40000。"""
    resp = client.get(FLOWS_URL, params={"flow_type": "unknown"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_list_stock_flows_requires_read_permission(
    client: TestClient, service: FakeStockService
) -> None:
    """缺少 stock:read：403 + 40300，且不进入 service。"""
    install_overrides(None, permissions=set(), stock=service)
    resp = client.get(FLOWS_URL)
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
    assert service.calls == []
