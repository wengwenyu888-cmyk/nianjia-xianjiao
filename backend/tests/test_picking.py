"""接口测试：分拣（TestClient + fake service，不连数据库）。

本地跑法（backend 目录下）：
    uv run pytest tests/test_picking.py -q
    # 或（本机 python 已装 fastapi/pydantic/pytest 时）：
    python -m pytest tests/test_picking.py -q

说明：SQLite 内存库与 MySQL 方言类型不兼容，故接口层用依赖注入替换 get_db /
get_current_user / get_summary_service（分拣与汇总同属 summary_service），
只断言路由装配、参数校验、40900 错误映射与统一响应结构，不连真实数据库；
FIFO 批次占用与 batch_stock/batch_flow 恒等式在 service 层测。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core.deps import PermissionCode
from app.core.exceptions import ConflictError
from app.main import app
from tests.fakes import FakeSummaryService, install_overrides, pick_row

PICKS_URL = "/api/v1/picks"
CREATE_PERMS = {PermissionCode.PICK_CREATE}
COMPLETE_PERMS = {PermissionCode.PICK_COMPLETE}


@pytest.fixture
def service() -> FakeSummaryService:
    return FakeSummaryService()


@pytest.fixture
def client(service: FakeSummaryService) -> Iterator[TestClient]:
    install_overrides(
        None,
        permissions={PermissionCode.PICK_CREATE, PermissionCode.PICK_COMPLETE},
        pick=service,
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------- POST /picks
def test_create_pick_route(client: TestClient, service: FakeSummaryService) -> None:
    """按门店生成分拣单：summary_id/store_id 透传，返回落定批次的明细。"""
    resp = client.post(
        PICKS_URL,
        json={"summary_id": 5, "store_id": 3},
        headers={"Idempotency-Key": "pick-1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0 and body["message"] == "ok"
    data = body["data"]
    assert data["pick_no"] == "FJ202610130001"
    assert data["status"] == "created"
    assert data["items"][0]["batch_no"] == "B20261001"
    _, kwargs = service.calls[-1]
    assert kwargs["payload"].summary_id == 5
    assert kwargs["payload"].store_id == 3
    assert kwargs["operator_id"] == 7
    assert kwargs["idempotency_key"] == "pick-1"


def test_create_pick_rejects_missing_summary_id(client: TestClient) -> None:
    """缺 summary_id 属参数校验：400 + 40000。"""
    resp = client.post(PICKS_URL, json={"store_id": 3})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_create_pick_insufficient_stock_is_40900(
    client: TestClient, service: FakeSummaryService
) -> None:
    """总部仓批次库存不足：service 抛 40900，接口层原样映射（扣减失败不入配送）。"""
    service.pick_error = ConflictError("总部仓批次库存不足：SKU 100 缺口 4.000")
    resp = client.post(PICKS_URL, json={"summary_id": 5, "store_id": 3})
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == 40900
    assert body["data"] is None
    assert "库存不足" in body["message"]


def test_create_pick_duplicate_pick_is_40900(
    client: TestClient, service: FakeSummaryService
) -> None:
    """该门店已存在分拣单（重复分拣）：409 + 40900。"""
    service.duplicate_pick_error = ConflictError(
        "该门店已存在分拣单，如需重拣请先取消原分拣单后重试"
    )
    resp = client.post(PICKS_URL, json={"summary_id": 5, "store_id": 3})
    assert resp.status_code == 409
    assert resp.json()["code"] == 40900


def test_create_pick_requires_create_permission(
    client: TestClient, service: FakeSummaryService
) -> None:
    """缺少 pick:create：403 + 40300，且不进入 service。"""
    install_overrides(None, permissions=COMPLETE_PERMS, pick=service)
    resp = client.post(PICKS_URL, json={"summary_id": 5, "store_id": 3})
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
    assert service.calls == []


# ----------------------------------------------------------------------- GET /picks
def test_list_picks_shape_and_filters(client: TestClient, service: FakeSummaryService) -> None:
    """分页查询：require_date / summary_id / store_id / status 全部透传。"""
    service.picks = [
        pick_row(id=1, summary_id=5, store_id=3, status="created"),
        pick_row(id=2, summary_id=5, store_id=9, status="done"),
    ]
    resp = client.get(
        PICKS_URL,
        params={
            "page": 1,
            "page_size": 10,
            "require_date": "2026-10-13",
            "summary_id": 5,
            "store_id": 3,
            "status": "created",
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert set(data) == {"list", "total", "page", "page_size"}
    assert data["total"] == 1
    assert data["list"][0]["pick_no"] == "FJ202610130001"
    _, kwargs = service.calls[-1]
    assert kwargs["require_date"] == date(2026, 10, 13)
    assert kwargs["summary_id"] == 5
    assert kwargs["store_id"] == 3
    assert kwargs["status"] == "created"


def test_list_picks_without_filters(client: TestClient, service: FakeSummaryService) -> None:
    """不传过滤条件：service 收到全 None。

    分拣单本身不存配送日，require_date 由服务层转查汇总单。
    """
    service.picks = [pick_row(id=1), pick_row(id=2, store_id=9)]
    resp = client.get(PICKS_URL)
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 2
    _, kwargs = service.calls[-1]
    assert kwargs["require_date"] is None
    assert kwargs["summary_id"] is None and kwargs["store_id"] is None
    assert kwargs["status"] is None


def test_list_picks_rejects_bad_date(client: TestClient) -> None:
    """require_date 非日期格式：400 + 40000。"""
    resp = client.get(PICKS_URL, params={"require_date": "2026-13-99"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_list_picks_rejects_zero_store_id(client: TestClient) -> None:
    """store_id 必须 ≥1：0 属参数校验 → 400 + 40000。"""
    resp = client.get(PICKS_URL, params={"store_id": 0})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


# ------------------------------------------------------- POST /picks/{id}/complete
def test_complete_pick_route(client: TestClient, service: FakeSummaryService) -> None:
    """分拣完成：created→done，返回 done 状态单。"""
    resp = client.post(f"{PICKS_URL}/7/complete", headers={"Idempotency-Key": "pick-2"})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "done"
    _, kwargs = service.calls[-1]
    assert kwargs["pick_id"] == 7
    assert kwargs["operator_id"] == 7


def test_complete_pick_requires_complete_permission(
    client: TestClient, service: FakeSummaryService
) -> None:
    """缺少 pick:complete：403 + 40300，且不进入 service。"""
    install_overrides(None, permissions=CREATE_PERMS, pick=service)
    resp = client.post(f"{PICKS_URL}/7/complete")
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
    assert service.calls == []


def test_complete_pick_rejects_zero_id(client: TestClient) -> None:
    """路径参数 pick_id 必须 ≥1：400 + 40000。"""
    resp = client.post(f"{PICKS_URL}/0/complete")
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000
