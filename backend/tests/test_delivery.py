"""接口测试：配送（TestClient + fake service，不连数据库）。

本地跑法（backend 目录下）：
    uv run pytest tests/test_delivery.py -q
    # 或（本机 python 已装 fastapi/pydantic/pytest 时）：
    python -m pytest tests/test_delivery.py -q

说明：SQLite 内存库与 MySQL 方言类型不兼容，故接口层用依赖注入替换 get_db /
get_current_user / get_delivery_service（签收单详情 /signs 见 test_receipt.py），
只断言路由装配、参数校验、数据范围（§8.1）与统一响应结构，不连真实数据库；
发车/签收的状态机与库存落定在 service 层测。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core.deps import PermissionCode
from app.core.exceptions import BusinessError, ConflictError
from app.main import app
from tests.fakes import (
    FakeDeliveryService,
    delivery_item_row,
    delivery_row,
    install_overrides,
    sign_row,
)

DELIVERIES_URL = "/api/v1/deliveries"
ALL_PERMS = {
    PermissionCode.DELIVERY_CREATE,
    PermissionCode.DELIVERY_READ,
    PermissionCode.DELIVERY_DEPART,
    PermissionCode.SIGN_CREATE,
}
SIGN_ITEM = {"sku_id": 100, "batch_no": "B20261001", "sign_qty_base": "8.000"}


@pytest.fixture
def service() -> FakeDeliveryService:
    return FakeDeliveryService()


@pytest.fixture
def client(service: FakeDeliveryService) -> Iterator[TestClient]:
    install_overrides(None, permissions=ALL_PERMS, delivery=service)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ------------------------------------------------------------------ POST /deliveries
def test_create_delivery_route(client: TestClient, service: FakeDeliveryService) -> None:
    """装车：落 loaded 配送单，明细随头返回，幂等键透传。"""
    resp = client.post(
        DELIVERIES_URL,
        json={
            "summary_id": 5,
            "store_id": 3,
            "require_date": "2026-10-13",
            "driver_id": 9,
            "plate_no": "沪A12345",
            "items": [{"sku_id": 100, "batch_no": "B20261001", "qty_base": "10.000"}],
        },
        headers={"Idempotency-Key": "ps-1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0 and body["message"] == "ok"
    data = body["data"]
    assert data["delivery_no"] == "PS202610130001"
    assert data["status"] == "loaded"
    assert data["store_id"] == 3
    assert data["plate_no"] == "沪A12345"
    assert data["items"][0]["batch_no"] == "B20261001"
    # 调用序列：create_delivery → list_delivery_items（装配明细）
    name, kwargs = service.calls[-2]
    assert name == "create_delivery"
    assert kwargs["payload"].summary_id == 5
    assert kwargs["operator_id"] == 7
    assert kwargs["idempotency_key"] == "ps-1"


def test_create_delivery_store_account_cross_store_is_40300(
    client: TestClient, service: FakeDeliveryService
) -> None:
    """门店账号为他店装车：403 + 40300（service 侧数据范围判定）。"""
    install_overrides(
        None,
        permissions=ALL_PERMS,
        role="store_manager",
        store_id=3,
        delivery=service,
    )
    resp = client.post(
        DELIVERIES_URL,
        json={
            "summary_id": 5,
            "store_id": 9,
            "require_date": "2026-10-13",
            "items": [{"sku_id": 100, "batch_no": "B20261001", "qty_base": "10.000"}],
        },
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_create_delivery_rejects_empty_items_list(client: TestClient) -> None:
    """显式传空 items 违反 min_length=1：400 + 40000。"""
    resp = client.post(
        DELIVERIES_URL,
        json={"summary_id": 5, "store_id": 3, "require_date": "2026-10-13", "items": []},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 40000
    assert body["data"]


def test_create_delivery_rejects_bad_date(client: TestClient) -> None:
    """require_date 非日期格式：400 + 40000。"""
    resp = client.post(
        DELIVERIES_URL, json={"summary_id": 5, "store_id": 3, "require_date": "13/10/2026"}
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_create_delivery_requires_create_permission(
    client: TestClient, service: FakeDeliveryService
) -> None:
    """缺少 delivery:create：403 + 40300，且不进入 service。"""
    install_overrides(None, permissions={PermissionCode.DELIVERY_READ}, delivery=service)
    resp = client.post(
        DELIVERIES_URL, json={"summary_id": 5, "store_id": 3, "require_date": "2026-10-13"}
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
    assert service.calls == []


# ------------------------------------------------------------------ GET /deliveries
def test_list_deliveries_shape_and_filters(
    client: TestClient, service: FakeDeliveryService
) -> None:
    """列表：driver_id / require_date / status 透传，分页结构固定。"""
    service.deliveries = [
        delivery_row(id=1, store_id=3, status="loaded", require_date=date(2026, 10, 13)),
        delivery_row(id=2, store_id=3, status="on_way", require_date=date(2026, 10, 14)),
    ]
    resp = client.get(
        DELIVERIES_URL,
        params={
            "page": 1,
            "page_size": 10,
            "driver_id": 9,
            "require_date": "2026-10-13",
            "status": "loaded",
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert set(data) == {"list", "total", "page", "page_size"}
    assert data["total"] == 1
    assert data["list"][0]["delivery_no"] == "PS202610130001"
    # 列表不带明细（防 N+1）
    assert data["list"][0]["items"] == []
    _, kwargs = service.calls[-1]
    assert kwargs["driver_id"] == 9
    assert kwargs["require_date"] == date(2026, 10, 13)
    assert kwargs["status"] == "loaded"
    assert kwargs["actor"].store_id is None


def test_list_deliveries_store_account_forced_to_own_store(
    client: TestClient, service: FakeDeliveryService
) -> None:
    """门店账号：actor.store_id 非空，service 强制只看本店。"""
    install_overrides(
        None,
        permissions={PermissionCode.DELIVERY_READ},
        role="store_manager",
        store_id=3,
        delivery=service,
    )
    service.deliveries = [
        delivery_row(id=1, store_id=3),
        delivery_row(id=2, store_id=9),
    ]
    resp = client.get(DELIVERIES_URL)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert {row["store_id"] for row in data["list"]} == {3}
    _, kwargs = service.calls[-1]
    assert kwargs["actor"].store_id == 3
    assert kwargs["actor"].roles == frozenset({"store_manager"})


def test_list_deliveries_driver_scoped_to_self(
    client: TestClient, service: FakeDeliveryService
) -> None:
    """纯司机：只看到本人任务；显式请求他人 driver_id → 403 + 40300。"""
    install_overrides(
        None,
        permissions={PermissionCode.DELIVERY_READ},
        role="driver",
        store_id=None,
        delivery=service,
    )
    service.deliveries = [
        delivery_row(id=1, driver_id=7, store_id=3),  # 本人（user_id=7）
        delivery_row(id=2, driver_id=10, store_id=3),  # 他人任务
    ]
    resp = client.get(DELIVERIES_URL)
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 1
    _, kwargs = service.calls[-1]
    assert kwargs["actor"].is_driver_scoped is True

    resp2 = client.get(DELIVERIES_URL, params={"driver_id": 10})
    assert resp2.status_code == 403
    assert resp2.json()["code"] == 40300


def test_list_deliveries_rejects_unknown_status(client: TestClient) -> None:
    """status 值域之外：400 + 40000。"""
    resp = client.get(DELIVERIES_URL, params={"status": "flying"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_list_deliveries_requires_read_permission(
    client: TestClient, service: FakeDeliveryService
) -> None:
    """缺少 delivery:read：403 + 40300。"""
    install_overrides(None, permissions={PermissionCode.SIGN_CREATE}, delivery=service)
    resp = client.get(DELIVERIES_URL)
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


# ------------------------------------------------------------ GET /deliveries/{id}
def test_get_delivery_route(client: TestClient, service: FakeDeliveryService) -> None:
    """详情：带全量明细与司机/车牌信息。"""
    resp = client.get(f"{DELIVERIES_URL}/1")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == 1
    assert data["driver_id"] == 9
    assert data["items"][0]["sku_id"] == 100
    _, kwargs = service.calls[-1]
    assert kwargs["delivery_id"] == 1


def test_get_delivery_store_account_other_store_is_40300(
    client: TestClient, service: FakeDeliveryService
) -> None:
    """门店账号看他店配送单：403 + 40300。"""
    install_overrides(
        None,
        permissions={PermissionCode.DELIVERY_READ},
        role="store_manager",
        store_id=9,
        delivery=service,
    )
    resp = client.get(f"{DELIVERIES_URL}/1")
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_get_delivery_driver_other_task_is_40300(
    client: TestClient, service: FakeDeliveryService
) -> None:
    """司机看他人任务：403 + 40300。"""
    install_overrides(
        None,
        permissions={PermissionCode.DELIVERY_READ},
        role="driver",
        store_id=None,
        delivery=service,
    )
    service.delivery = delivery_row(id=1, driver_id=10)
    resp = client.get(f"{DELIVERIES_URL}/1")
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


# ---------------------------------------------------- POST /deliveries/{id}/depart
def test_depart_delivery_route(client: TestClient, service: FakeDeliveryService) -> None:
    """发车：loaded→on_way，返回 on_way 状态单。"""
    resp = client.post(f"{DELIVERIES_URL}/2/depart")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "on_way"
    _, kwargs = service.calls[-1]
    assert kwargs["delivery_id"] == 2
    assert kwargs["operator_id"] == 7


def test_depart_delivery_illegal_transition_is_40900(
    client: TestClient, service: FakeDeliveryService
) -> None:
    """未装车/已签收等非法流转：service 抛 40900（loaded→on_way 以外的状态不可发车）。"""
    service.depart_error = ConflictError("配送单状态 signed 不能流转到 on_way")
    resp = client.post(f"{DELIVERIES_URL}/2/depart")
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == 40900
    assert body["data"] is None


def test_depart_delivery_store_account_is_40300(
    client: TestClient, service: FakeDeliveryService
) -> None:
    """门店账号无发车权限（service 侧 assert_can_depart）：403 + 40300。"""
    install_overrides(
        None,
        permissions=ALL_PERMS,
        role="store_manager",
        store_id=3,
        delivery=service,
    )
    resp = client.post(f"{DELIVERIES_URL}/2/depart")
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_depart_delivery_requires_depart_permission(
    client: TestClient, service: FakeDeliveryService
) -> None:
    """缺少 delivery:depart：403 + 40300，且不进入 service。"""
    install_overrides(None, permissions={PermissionCode.DELIVERY_READ}, delivery=service)
    resp = client.post(f"{DELIVERIES_URL}/2/depart")
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
    assert service.calls == []


# ------------------------------------------------------ POST /deliveries/{id}/sign
def test_sign_delivery_route(client: TestClient, service: FakeDeliveryService) -> None:
    """签收：写 sign+sign_item，返回差异生成列与关联配送单号。"""
    service.items = [delivery_item_row()]  # 配送单只有一条明细，本次上报正好覆盖
    resp = client.post(
        f"{DELIVERIES_URL}/1/sign",
        json={"items": [SIGN_ITEM], "remark": "少送 2kg"},
        headers={"Idempotency-Key": "sign-1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["delivery_id"] == 1
    assert data["delivery_no"] == "PS202610130001"
    assert data["status"] == "partial"
    assert data["items"][0]["diff_qty_base"] == "2.000"
    # 调用序列：sign → get_sign（装配签收单详情）
    name, kwargs = service.calls[-2]
    assert name == "sign"
    assert kwargs["delivery_id"] == 1
    assert kwargs["payload"].remark == "少送 2kg"
    assert kwargs["operator_id"] == 7
    assert kwargs["idempotency_key"] == "sign-1"


def test_sign_delivery_missing_items_is_400(
    client: TestClient, service: FakeDeliveryService
) -> None:
    """明细未覆盖配送单全部明细（缺行）：400 + 40000。"""
    service.items = [
        delivery_item_row(id=41, sku_id=100, batch_no="B20261001"),
        delivery_item_row(id=42, sku_id=101, batch_no="B20261002"),
    ]
    resp = client.post(f"{DELIVERIES_URL}/1/sign", json={"items": [SIGN_ITEM]})
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 40000
    assert body["data"] is None


def test_sign_delivery_empty_items_is_validation_error(client: TestClient) -> None:
    """items 为空违反 min_length=1：400 + 40000（不进 service）。"""
    resp = client.post(f"{DELIVERIES_URL}/1/sign", json={"items": []})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_sign_delivery_duplicate_item_is_validation_error(client: TestClient) -> None:
    """同 (sku_id, batch_no) 重复上报：模型校验失败 → 400 + 40000。"""
    resp = client.post(
        f"{DELIVERIES_URL}/1/sign",
        json={"items": [SIGN_ITEM, dict(SIGN_ITEM, sign_qty_base="1.000")]},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_sign_delivery_store_account_other_store_is_40300(
    client: TestClient, service: FakeDeliveryService
) -> None:
    """门店账号签收他店配送单：403 + 40300。"""
    install_overrides(
        None,
        permissions=ALL_PERMS,
        role="store_manager",
        store_id=9,
        delivery=service,
    )
    service.delivery = delivery_row(id=1, store_id=3)
    service.sign_row = sign_row(store_id=3)
    resp = client.post(f"{DELIVERIES_URL}/1/sign", json={"items": [SIGN_ITEM]})
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_sign_delivery_requires_sign_permission(
    client: TestClient, service: FakeDeliveryService
) -> None:
    """缺少 sign:create：403 + 40300，且不进入 service。"""
    install_overrides(None, permissions={PermissionCode.DELIVERY_READ}, delivery=service)
    resp = client.post(f"{DELIVERIES_URL}/1/sign", json={"items": [SIGN_ITEM]})
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
    assert service.calls == []


def test_sign_delivery_inconsistent_status_is_400(
    client: TestClient, service: FakeDeliveryService
) -> None:
    """显式 status 与明细推导不一致：service 抛 40000。"""
    service.sign_error = BusinessError("签收状态 full 与明细差异推导结果 partial 不一致")
    resp = client.post(f"{DELIVERIES_URL}/1/sign", json={"items": [SIGN_ITEM], "status": "full"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000
