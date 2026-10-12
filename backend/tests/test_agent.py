"""接口测试：智能体建议（TestClient + fake service，不连数据库）。

本地跑法（backend 目录下）：
    uv run pytest tests/test_agent.py -q
    # 或（本机 python 已装 fastapi/pydantic/pytest 时）：
    python -m pytest tests/test_agent.py -q

说明：SQLite 内存库与 MySQL 方言类型不兼容，故接口层用依赖注入替换 get_db /
get_current_user / get_agent_service，只断言路由装配、参数校验、数据范围（§8.1）
与统一响应结构，不连真实数据库；规则版建议算法（rule-v1）在 service 层测。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core.deps import PermissionCode
from app.core.exceptions import ConflictError
from app.main import app
from tests.fakes import FakeAgentService, install_overrides, suggestion_row

SUGGESTIONS_URL = "/api/v1/agent/order-suggestions"
PICK_PLAN_URL = "/api/v1/agent/pick-plan"
ALL_PERMS = {
    PermissionCode.AGENT_SUGGEST,
    PermissionCode.AGENT_READ,
    PermissionCode.AGENT_APPLY,
    PermissionCode.AGENT_PICK_PLAN,
}


@pytest.fixture
def service() -> FakeAgentService:
    return FakeAgentService()


@pytest.fixture
def client(service: FakeAgentService) -> Iterator[TestClient]:
    install_overrides(None, permissions=ALL_PERMS, agent=service)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ------------------------------------------------- POST /agent/order-suggestions
def test_generate_suggestions_route(client: TestClient, service: FakeAgentService) -> None:
    """生成建议快照：默认 pending、payload 为生成当时依据，「只建议不落账」。"""
    resp = client.post(
        SUGGESTIONS_URL,
        json={"store_id": 3, "require_date": "2026-10-13"},
        headers={"Idempotency-Key": "sug-1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0 and body["message"] == "ok"
    data = body["data"]
    assert data["suggestion_type"] == "order_suggest"
    assert data["store_id"] == 3
    assert data["apply_status"] == "pending"
    assert data["payload"]["policy"] == "rule-v1"
    assert data["payload"]["items"][0]["sku_id"] == 100
    _, kwargs = service.calls[-1]
    assert kwargs["payload"].require_date == date(2026, 10, 13)
    assert kwargs["operator_id"] == 7
    assert kwargs["idempotency_key"] == "sug-1"


def test_generate_suggestions_store_account_defaults_to_own_store(
    client: TestClient, service: FakeAgentService
) -> None:
    """门店账号可省略 store_id：取本人 store_id 并作为数据范围传给 service。"""
    install_overrides(None, permissions=ALL_PERMS, role="store_manager", store_id=3, agent=service)
    resp = client.post(SUGGESTIONS_URL, json={"require_date": "2026-10-13"})
    assert resp.status_code == 200
    assert resp.json()["data"]["store_id"] == 3
    _, kwargs = service.calls[-1]
    assert kwargs["store_id_scope"] == 3


def test_generate_suggestions_cross_store_is_40300(
    client: TestClient, service: FakeAgentService
) -> None:
    """门店账号为他店生成建议：403 + 40300。"""
    install_overrides(None, permissions=ALL_PERMS, role="store_manager", store_id=3, agent=service)
    resp = client.post(SUGGESTIONS_URL, json={"store_id": 9, "require_date": "2026-10-13"})
    assert resp.status_code == 403
    body = resp.json()
    assert body["code"] == 40300
    assert body["data"] is None


def test_generate_suggestions_missing_require_date(client: TestClient) -> None:
    """缺 require_date 属参数校验：400 + 40000。"""
    resp = client.post(SUGGESTIONS_URL, json={"store_id": 3})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_generate_suggestions_requires_suggest_permission(
    client: TestClient, service: FakeAgentService
) -> None:
    """缺少 agent:suggest：403 + 40300，且不进入 service。"""
    install_overrides(None, permissions={PermissionCode.AGENT_READ}, role="admin", agent=service)
    resp = client.post(SUGGESTIONS_URL, json={"store_id": 3, "require_date": "2026-10-13"})
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
    assert service.calls == []


# --------------------------------------------- GET /agent/order-suggestions/{id}
def test_get_suggestion_route(client: TestClient, service: FakeAgentService) -> None:
    """查看建议快照：返回 payload 依据，suggestion_id 透传。"""
    resp = client.get(f"{SUGGESTIONS_URL}/12")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["id"] == 1
    assert body["data"]["model"] == "rule-v1"
    _, kwargs = service.calls[-1]
    assert kwargs["suggestion_id"] == 12


def test_get_suggestion_store_account_other_store_is_40300(
    client: TestClient, service: FakeAgentService
) -> None:
    """门店账号查看他店建议：403 + 40300。"""
    install_overrides(
        None,
        permissions={PermissionCode.AGENT_READ},
        role="store_manager",
        store_id=9,
        agent=service,
    )
    resp = client.get(f"{SUGGESTIONS_URL}/12")
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_get_suggestion_store_account_own_store_ok(
    client: TestClient, service: FakeAgentService
) -> None:
    """门店账号查看本店建议（store_id 与建议一致）：200。"""
    install_overrides(
        None,
        permissions={PermissionCode.AGENT_READ},
        role="store_manager",
        store_id=3,
        agent=service,
    )
    resp = client.get(f"{SUGGESTIONS_URL}/12")
    assert resp.status_code == 200
    assert resp.json()["data"]["store_id"] == 3


def test_get_suggestion_requires_read_permission(
    client: TestClient, service: FakeAgentService
) -> None:
    """缺少 agent:read：403 + 40300。"""
    install_overrides(None, permissions={PermissionCode.AGENT_SUGGEST}, agent=service)
    resp = client.get(f"{SUGGESTIONS_URL}/12")
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


# --------------------------------------- POST /agent/order-suggestions/{id}/apply
def test_apply_suggestion_creates_draft_order(
    client: TestClient, service: FakeAgentService
) -> None:
    """采纳建议：只生成 draft 要货单（source=agent 并回指建议 id），仍须店长 confirm。"""
    resp = client.post(f"{SUGGESTIONS_URL}/12/apply", headers={"Idempotency-Key": "apply-1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["status"] == "draft"
    assert data["source"] == "agent"
    assert data["agent_suggestion_id"] == 12
    _, kwargs = service.calls[-1]
    assert kwargs["suggestion_id"] == 12
    assert kwargs["operator_id"] == 7
    assert kwargs["idempotency_key"] == "apply-1"


def test_apply_suggestion_not_pending_is_40900(
    client: TestClient, service: FakeAgentService
) -> None:
    """建议已被采纳/拒绝（非 pending）：409 + 40900。"""
    service.suggestion = suggestion_row(apply_status="applied", order_id=88)
    resp = client.post(f"{SUGGESTIONS_URL}/12/apply")
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == 40900
    assert body["data"] is None


def test_apply_suggestion_requires_apply_permission(
    client: TestClient, service: FakeAgentService
) -> None:
    """缺少 agent:apply：403 + 40300。"""
    install_overrides(None, permissions={PermissionCode.AGENT_READ}, agent=service)
    resp = client.post(f"{SUGGESTIONS_URL}/12/apply")
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


# ------------------------------------------------------ POST /agent/pick-plan
def test_create_pick_plan_route(client: TestClient, service: FakeAgentService) -> None:
    """配货计划（只读 FIFO 预演）：返回任务行、批次预演与缺口，并带 suggestion_id。"""
    resp = client.post(
        PICK_PLAN_URL,
        json={"require_date": "2026-10-13"},
        headers={"Idempotency-Key": "plan-1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["suggestion_id"] == 2
    assert data["policy"] == "rule-v1"
    assert data["require_date"] == "2026-10-13"
    assert data["tasks"][0]["store_id"] == 3
    assert data["tasks"][0]["shortage_qty_base"] == "2.000"
    assert data["tasks"][0]["batches"][0]["batch_no"] == "B20261001"
    assert data["total_shortage_qty_base"] == "2.000"
    _, kwargs = service.calls[-1]
    assert kwargs["payload"].require_date == date(2026, 10, 13)
    assert kwargs["operator_id"] == 7
    assert kwargs["idempotency_key"] == "plan-1"


def test_create_pick_plan_missing_require_date(client: TestClient) -> None:
    """缺 require_date 属参数校验：400 + 40000。"""
    resp = client.post(PICK_PLAN_URL, json={})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_create_pick_plan_requires_permission(
    client: TestClient, service: FakeAgentService
) -> None:
    """缺少 agent:pick_plan：403 + 40300。"""
    install_overrides(None, permissions={PermissionCode.AGENT_SUGGEST}, agent=service)
    resp = client.post(PICK_PLAN_URL, json={"require_date": "2026-10-13"})
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_apply_suggestion_conflict_from_service_is_40900(
    client: TestClient, service: FakeAgentService
) -> None:
    """service 侧抛 40900（建议无可采纳明细）：接口层原样映射。"""

    def _raise(*args: object, **kwargs: object) -> None:
        raise ConflictError("建议没有可采纳的明细")

    service.apply_suggestion = _raise  # type: ignore[method-assign]
    resp = client.post(f"{SUGGESTIONS_URL}/12/apply")
    assert resp.status_code == 409
    assert resp.json()["code"] == 40900
