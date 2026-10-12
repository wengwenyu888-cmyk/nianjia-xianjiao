"""接口测试：汇总（TestClient + fake service，不连数据库）。

本地跑法（backend 目录下）：
    uv run pytest tests/test_summary.py -q
    # 或（本机 python 已装 fastapi/pydantic/pytest 时）：
    python -m pytest tests/test_summary.py -q

说明：SQLite 内存库与 MySQL 方言类型不兼容，故接口层用依赖注入替换 get_db /
get_current_user / get_summary_service，只断言路由装配、参数校验与统一响应结构，
不连真实数据库（汇总口径与 uk_req_date 幂等在 service 层）。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core.deps import PermissionCode
from app.main import app
from tests.fakes import FakeSummaryService, install_overrides, summary_row

SUMMARIES_URL = "/api/v1/summaries"
GENERATE_PERMS = {PermissionCode.SUMMARY_GENERATE}
READ_PERMS = {PermissionCode.SUMMARY_READ}


@pytest.fixture
def service() -> FakeSummaryService:
    return FakeSummaryService()


@pytest.fixture
def client(service: FakeSummaryService) -> Iterator[TestClient]:
    install_overrides(
        None,
        permissions={PermissionCode.SUMMARY_GENERATE, PermissionCode.SUMMARY_READ},
        summary=service,
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --------------------------------------------------------- POST /summaries/generate
def test_generate_summary_route(client: TestClient, service: FakeSummaryService) -> None:
    """按配送日生成汇总单：require_date 与操作人透传，返回 SKU 汇总明细。"""
    resp = client.post(
        f"{SUMMARIES_URL}/generate",
        json={"require_date": "2026-10-13"},
        headers={"Idempotency-Key": "sum-1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0 and body["message"] == "ok"
    data = body["data"]
    assert data["summary_no"] == "HZ202610130001"
    assert data["require_date"] == "2026-10-13"
    assert data["status"] == "generated"
    assert data["items"][0]["total_qty_base"] == "30.000"
    _, kwargs = service.calls[-1]
    assert kwargs["require_date"] == date(2026, 10, 13)
    assert kwargs["operator_id"] == 7
    assert kwargs["idempotency_key"] == "sum-1"


def test_generate_summary_missing_require_date_is_validation_error(client: TestClient) -> None:
    """缺 require_date 属参数校验：400 + 40000。"""
    resp = client.post(f"{SUMMARIES_URL}/generate", json={})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_generate_summary_requires_generate_permission(
    client: TestClient, service: FakeSummaryService
) -> None:
    """缺少 summary:generate（门店账号无该权限点）：403 + 40300，且不进入 service。"""
    install_overrides(None, permissions=READ_PERMS, summary=service)
    resp = client.post(f"{SUMMARIES_URL}/generate", json={"require_date": "2026-10-13"})
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
    assert service.calls == []


# ------------------------------------------------------------------ GET /summaries
def test_list_summaries_shape_and_filters(client: TestClient, service: FakeSummaryService) -> None:
    """分页查询：require_date / status 透传，响应为统一分页结构。"""
    service.summaries = [
        summary_row(id=1, require_date=date(2026, 10, 13), status="generated"),
        summary_row(id=2, require_date=date(2026, 10, 14), status="picking"),
    ]
    resp = client.get(
        SUMMARIES_URL,
        params={"page": 3, "page_size": 5, "require_date": "2026-10-13", "status": "generated"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert set(data) == {"list", "total", "page", "page_size"}
    assert data["total"] == 1
    assert data["page"] == 3 and data["page_size"] == 5
    assert data["list"][0]["summary_no"] == "HZ202610130001"
    _, kwargs = service.calls[-1]
    assert kwargs["require_date"] == date(2026, 10, 13)
    assert kwargs["status"] == "generated"
    assert kwargs["page"] == 3 and kwargs["page_size"] == 5


def test_list_summaries_without_filters(client: TestClient, service: FakeSummaryService) -> None:
    """不传过滤条件：service 收到 None，返回全部汇总单。"""
    service.summaries = [summary_row(id=1), summary_row(id=2, status="done")]
    resp = client.get(SUMMARIES_URL)
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 2
    _, kwargs = service.calls[-1]
    assert kwargs["require_date"] is None and kwargs["status"] is None


def test_list_summaries_rejects_unknown_status(client: TestClient) -> None:
    """status 值域之外：400 + 40000。"""
    resp = client.get(SUMMARIES_URL, params={"status": "unknown"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_list_summaries_rejects_bad_date(client: TestClient) -> None:
    """require_date 非 YYYY-MM-DD：400 + 40000。"""
    resp = client.get(SUMMARIES_URL, params={"require_date": "2026/10/13"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_list_summaries_requires_read_permission(
    client: TestClient, service: FakeSummaryService
) -> None:
    """缺少 summary:read：403 + 40300。"""
    install_overrides(None, permissions=GENERATE_PERMS, summary=service)
    resp = client.get(SUMMARIES_URL)
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
