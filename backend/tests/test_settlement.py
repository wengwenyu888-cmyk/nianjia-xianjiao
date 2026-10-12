"""接口测试：对账核算（TestClient + fake service，不连数据库）。

本地跑法（backend 目录下）：
    uv run pytest tests/test_settlement.py -q
    # 或（本机 python 已装 fastapi/pydantic/pytest 时）：
    python -m pytest tests/test_settlement.py -q

说明：SQLite 内存库与 MySQL 方言类型不兼容，故接口层用依赖注入替换 get_db /
get_current_user / get_settlement_service，只断言路由装配、参数校验、数据范围（§8.1）
与统一响应结构；周期解析与 SQL 聚合口径在 service 层测。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.deps import PermissionCode
from app.main import app
from tests.fakes import (
    FakeSettlementService,
    install_overrides,
    reconcile_row,
    store_kpi_result,
    store_profit_result,
)

RECONCILES_URL = "/api/v1/reconciles"
PROFIT_URL = "/api/v1/stores/3/profit"
KPI_URL = "/api/v1/stores/3/kpi"
ALL_PERMS = {
    PermissionCode.RECONCILE_GENERATE,
    PermissionCode.RECONCILE_READ,
    PermissionCode.RECONCILE_CONFIRM,
    PermissionCode.REPORT_PROFIT,
    PermissionCode.REPORT_KPI,
}


@pytest.fixture
def service() -> FakeSettlementService:
    return FakeSettlementService()


@pytest.fixture
def client(service: FakeSettlementService) -> Iterator[TestClient]:
    install_overrides(None, permissions=ALL_PERMS, settlement=service)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ------------------------------------------------------ POST /reconciles/generate
def test_generate_reconcile_route(client: TestClient, service: FakeSettlementService) -> None:
    """按周期生成对账单：period/store_ids 透传，返回 generated/reused 计数。"""
    resp = client.post(
        f"{RECONCILES_URL}/generate",
        json={"period": "2026-W42", "store_ids": [3]},
        headers={"Idempotency-Key": "rec-1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0 and body["message"] == "ok"
    data = body["data"]
    assert data["period"] == "2026-W42"
    assert data["generated"] == 1 and data["reused"] == 0
    assert data["list"][0]["store_id"] == 3
    _, kwargs = service.calls[-1]
    assert kwargs["period"] == "2026-W42"
    assert kwargs["store_ids"] == [3]
    assert kwargs["operator_id"] == 7
    assert kwargs["idempotency_key"] == "rec-1"


def test_generate_reconcile_without_store_ids(
    client: TestClient, service: FakeSettlementService
) -> None:
    """store_ids 缺省：service 收到 None（=该周期有签收数据的全部门店）。"""
    resp = client.post(f"{RECONCILES_URL}/generate", json={"period": "2026-10"})
    assert resp.status_code == 200
    _, kwargs = service.calls[-1]
    assert kwargs["store_ids"] is None


def test_generate_reconcile_store_scope_is_40300(
    client: TestClient, service: FakeSettlementService
) -> None:
    """门店账号为指定他店生成对账：403 + 40300。"""
    install_overrides(
        None,
        permissions=ALL_PERMS,
        role="store_manager",
        store_id=3,
        settlement=service,
    )
    resp = client.post(f"{RECONCILES_URL}/generate", json={"period": "2026-W42", "store_ids": [9]})
    assert resp.status_code == 403
    body = resp.json()
    assert body["code"] == 40300
    assert body["data"] is None


def test_generate_reconcile_rejects_bad_period(client: TestClient) -> None:
    """period 长度不足（min_length=4）：400 + 40000。"""
    resp = client.post(f"{RECONCILES_URL}/generate", json={"period": "1"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_generate_reconcile_rejects_empty_store_ids(client: TestClient) -> None:
    """store_ids 显式传空数组违反 min_length=1：400 + 40000。"""
    resp = client.post(f"{RECONCILES_URL}/generate", json={"period": "2026-W42", "store_ids": []})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_generate_reconcile_requires_generate_permission(
    client: TestClient, service: FakeSettlementService
) -> None:
    """缺少 reconcile:generate：403 + 40300，且不进入 service。"""
    install_overrides(None, permissions={PermissionCode.RECONCILE_READ}, settlement=service)
    resp = client.post(f"{RECONCILES_URL}/generate", json={"period": "2026-W42"})
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
    assert service.calls == []


# ------------------------------------------------------------------ GET /reconciles
def test_list_reconciles_shape_and_filters(
    client: TestClient, service: FakeSettlementService
) -> None:
    """分页查询：period/store_id 透传，响应为统一分页结构。"""
    service.reconciles = [
        reconcile_row(id=1, period="2026-W42", store_id=3),
        reconcile_row(id=2, period="2026-W41", store_id=3),
    ]
    resp = client.get(
        RECONCILES_URL, params={"page": 2, "page_size": 5, "period": "2026-W42", "store_id": 3}
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert set(data) == {"list", "total", "page", "page_size"}
    assert data["total"] == 1
    assert data["page"] == 2 and data["page_size"] == 5
    assert data["list"][0]["period"] == "2026-W42"
    _, kwargs = service.calls[-1]
    assert kwargs["period"] == "2026-W42"
    assert kwargs["store_id"] == 3


def test_list_reconciles_store_account_injects_own_store(
    client: TestClient, service: FakeSettlementService
) -> None:
    """门店账号不传 store_id：强制注入本店。"""
    install_overrides(
        None,
        permissions={PermissionCode.RECONCILE_READ},
        role="store_manager",
        store_id=3,
        settlement=service,
    )
    service.reconciles = [reconcile_row(id=1, store_id=3), reconcile_row(id=2, store_id=9)]
    resp = client.get(RECONCILES_URL)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert {row["store_id"] for row in data["list"]} == {3}
    _, kwargs = service.calls[-1]
    assert kwargs["store_id"] == 3


def test_list_reconciles_store_account_other_store_is_40300(
    client: TestClient, service: FakeSettlementService
) -> None:
    """门店账号显式查他店对账：403 + 40300。"""
    install_overrides(
        None,
        permissions={PermissionCode.RECONCILE_READ},
        role="store_manager",
        store_id=3,
        settlement=service,
    )
    resp = client.get(RECONCILES_URL, params={"store_id": 9})
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_list_reconciles_rejects_short_period(client: TestClient) -> None:
    """period 长度不足：400 + 40000。"""
    resp = client.get(RECONCILES_URL, params={"period": "42"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_list_reconciles_requires_read_permission(
    client: TestClient, service: FakeSettlementService
) -> None:
    """缺少 reconcile:read：403 + 40300。"""
    install_overrides(None, permissions={PermissionCode.RECONCILE_GENERATE}, settlement=service)
    resp = client.get(RECONCILES_URL)
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


# ------------------------------------------------------- POST /reconciles/{id}/confirm
def test_confirm_reconcile_route(client: TestClient, service: FakeSettlementService) -> None:
    """确认对账：记录差异额并推进状态，确认人与幂等键透传。"""
    resp = client.post(
        f"{RECONCILES_URL}/8/confirm",
        json={"diff_amount": "12.34", "status": "confirmed"},
        headers={"Idempotency-Key": "rec-2"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == 8
    assert data["status"] == "confirmed"
    assert data["diff_amount"] == "12.34"
    assert data["confirmed_by"] == 7
    _, kwargs = service.calls[-1]
    assert kwargs["reconcile_id"] == 8
    assert str(kwargs["payload"].diff_amount) == "12.34"
    assert kwargs["operator_id"] == 7
    assert kwargs["idempotency_key"] == "rec-2"


def test_confirm_reconcile_defaults(client: TestClient, service: FakeSettlementService) -> None:
    """不传请求体字段：diff_amount 默认 0、status 默认 confirmed。"""
    resp = client.post(f"{RECONCILES_URL}/8/confirm", json={})
    assert resp.status_code == 200
    _, kwargs = service.calls[-1]
    assert str(kwargs["payload"].diff_amount) == "0"
    assert kwargs["payload"].status == "confirmed"


def test_confirm_reconcile_rejects_unknown_status(client: TestClient) -> None:
    """status 值域之外：400 + 40000。"""
    resp = client.post(f"{RECONCILES_URL}/8/confirm", json={"status": "cancelled"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_confirm_reconcile_requires_confirm_permission(
    client: TestClient, service: FakeSettlementService
) -> None:
    """缺少 reconcile:confirm：403 + 40300。"""
    install_overrides(None, permissions={PermissionCode.RECONCILE_READ}, settlement=service)
    resp = client.post(f"{RECONCILES_URL}/8/confirm", json={})
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


# -------------------------------------------------------- GET /stores/{id}/profit
def test_store_profit_route(client: TestClient, service: FakeSettlementService) -> None:
    """门店盈亏：收入-配货成本=利润，收入来源与对账单口径一并返回。"""
    resp = client.get(PROFIT_URL, params={"period": "2026-W42", "revenue": "3000.00"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["store_id"] == 3
    assert data["store_no"] == "S003"
    assert data["period"] == "2026-W42"
    assert data["revenue"] == "3000.00"
    assert data["revenue_source"] == "external"
    assert data["delivery_cost"] == "1200.00"
    assert data["gross_profit"] == "1800.00"
    assert data["gross_margin"] == "0.6000"
    assert data["reconcile_status"] == "draft"
    _, kwargs = service.calls[-1]
    assert kwargs["store_id"] == 3
    assert kwargs["period"] == "2026-W42"
    assert str(kwargs["revenue"]) == "3000.00"
    assert kwargs["actor"].store_id is None


def test_store_profit_without_revenue_marks_unavailable(
    client: TestClient, service: FakeSettlementService
) -> None:
    """不传 revenue：service 收到 None，响应标注无数据源（不把 0 当真实流水）。"""
    service.profit = store_profit_result(
        revenue="0.00", revenue_source="unavailable", gross_profit="-1200.00", gross_margin=None
    )
    resp = client.get(PROFIT_URL, params={"period": "2026-W42"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["revenue_source"] == "unavailable"
    assert data["gross_margin"] is None
    _, kwargs = service.calls[-1]
    assert kwargs["revenue"] is None


def test_store_profit_requires_period(client: TestClient) -> None:
    """period 为必填查询参数：缺省 400 + 40000。"""
    resp = client.get(PROFIT_URL)
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_store_profit_negative_revenue_is_validation_error(client: TestClient) -> None:
    """revenue 不允许负数（ge=0）：400 + 40000。"""
    resp = client.get(PROFIT_URL, params={"period": "2026-W42", "revenue": "-1"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_store_profit_store_account_other_store_is_40300(
    client: TestClient, service: FakeSettlementService
) -> None:
    """门店账号查看他店盈亏：403 + 40300。"""
    install_overrides(
        None,
        permissions={PermissionCode.REPORT_PROFIT},
        role="store_manager",
        store_id=9,
        settlement=service,
    )
    resp = client.get(PROFIT_URL, params={"period": "2026-W42"})
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_store_profit_requires_profit_permission(
    client: TestClient, service: FakeSettlementService
) -> None:
    """缺少 report:profit：403 + 40300。"""
    install_overrides(None, permissions={PermissionCode.REPORT_KPI}, settlement=service)
    resp = client.get(PROFIT_URL, params={"period": "2026-W42"})
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


# ----------------------------------------------------------- GET /stores/{id}/kpi
def test_store_kpi_route(client: TestClient, service: FakeSettlementService) -> None:
    """门店 KPI：损耗率/要货准确率/配送准确率/周转天数一次返回。"""
    resp = client.get(KPI_URL, params={"period": "2026-W42"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["store_id"] == 3
    assert data["period"] == "2026-W42"
    assert data["gross_in_qty_base"] == "8.000"
    assert data["loss_rate"] == "0.2500"
    assert data["order_accuracy"] == "0.8000"
    assert data["delivery_accuracy"] == "0.8000"
    assert data["turnover_days"] == "5.83"
    _, kwargs = service.calls[-1]
    assert kwargs["store_id"] == 3
    assert kwargs["period"] == "2026-W42"


def test_store_kpi_no_data_ratio_is_null(
    client: TestClient, service: FakeSettlementService
) -> None:
    """无分母时比值为 null（不返回 0 冒充「无数据」）。"""
    service.kpi = store_kpi_result(loss_rate=None, order_accuracy=None, turnover_days=None)
    resp = client.get(KPI_URL, params={"period": "2026-W42"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["loss_rate"] is None
    assert data["order_accuracy"] is None
    assert data["turnover_days"] is None


def test_store_kpi_requires_period(client: TestClient) -> None:
    """period 必填：缺省 400 + 40000。"""
    resp = client.get(KPI_URL)
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_store_kpi_store_account_other_store_is_40300(
    client: TestClient, service: FakeSettlementService
) -> None:
    """门店账号查看他店 KPI：403 + 40300。"""
    install_overrides(
        None,
        permissions={PermissionCode.REPORT_KPI},
        role="store_manager",
        store_id=9,
        settlement=service,
    )
    resp = client.get(KPI_URL, params={"period": "2026-W42"})
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_store_kpi_requires_kpi_permission(
    client: TestClient, service: FakeSettlementService
) -> None:
    """缺少 report:kpi：403 + 40300。"""
    install_overrides(None, permissions={PermissionCode.REPORT_PROFIT}, settlement=service)
    resp = client.get(KPI_URL, params={"period": "2026-W42"})
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
