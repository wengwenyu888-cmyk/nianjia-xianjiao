"""接口测试：认证（TestClient + fake auth service，不连数据库）。

本地跑法（backend 目录下）：
    uv run pytest tests/test_auth.py -q
    # 或用本机 python（需 fastapi/pydantic/pytest；jose/passlib/slowapi 非必需）：
    python -m pytest tests/test_auth.py -q

说明：
- fake service 不触碰数据库，也不做 bcrypt / JWT 签名，故本文件在缺 jose / passlib
  的环境下也能跑；真实校验与签发逻辑在 app/service/auth_service.py。
- /auth/me 的 Bearer 校验由 tests.fakes.install_auth_overrides 的替身完成。
- 登录三类失败（用户不存在 / 口令错误 / 已软删）必须返回完全一致的响应体，防账号枚举。
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.fakes import FakeAuthService, install_auth_overrides

LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/auth/me"

# 防枚举：三类失败共用同一文案，响应体必须逐字节一致
LOGIN_FAIL_MESSAGE = "用户名或密码错误"


@pytest.fixture
def auth_service() -> FakeAuthService:
    return FakeAuthService()


@pytest.fixture
def client(auth_service: FakeAuthService) -> Iterator[TestClient]:
    install_auth_overrides(auth_service)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _login(client: TestClient, username: str, password: str):
    """发一次登录请求并返回响应。"""
    return client.post(LOGIN_URL, json={"username": username, "password": password})


def test_login_success_returns_token_and_user(
    client: TestClient, auth_service: FakeAuthService
) -> None:
    """登录成功：统一响应 code=0，data 含 token/bearer/用户信息与权限点。"""
    resp = _login(client, "zhangsan", "St0re#2026")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0 and body["message"] == "ok"

    data = body["data"]
    assert set(data) == {"token", "token_type", "user"}
    assert data["token"] == auth_service.token and data["token"]
    assert data["token_type"] == "bearer"

    user = data["user"]
    assert set(user) == {
        "id",
        "username",
        "display_name",
        "store_id",
        "role_codes",
        "permission_codes",
    }
    assert user["id"] == 7
    assert user["username"] == "zhangsan"
    assert user["display_name"] == "张三"
    assert user["store_id"] == 3
    assert user["role_codes"] == ["store_manager"]
    assert user["permission_codes"] == ["master:store:read", "order:create"]

    # 口令与哈希绝不进响应体
    assert "password" not in json.dumps(body, ensure_ascii=False)
    assert auth_service.calls == [("zhangsan", "St0re#2026")]


def test_login_wrong_password_returns_40100(client: TestClient) -> None:
    """口令错误：401 + 40100，且不提示具体原因。"""
    resp = _login(client, "zhangsan", "wrong-password")
    assert resp.status_code == 401
    body = resp.json()
    assert body["code"] == 40100
    assert body["message"] == LOGIN_FAIL_MESSAGE
    assert body["data"] is None


def test_login_unknown_user_returns_same_40100(client: TestClient) -> None:
    """用户不存在：与口令错误完全同一响应（防枚举）。"""
    resp = _login(client, "nobody", "St0re#2026")
    assert resp.status_code == 401
    body = resp.json()
    assert body["code"] == 40100
    assert body["message"] == LOGIN_FAIL_MESSAGE


def test_login_soft_deleted_user_rejected(client: TestClient) -> None:
    """软删/停用用户：即使口令正确也拒绝，且响应与其它失败一致。"""
    resp = _login(client, "lisi", "St0re#2026")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


def test_login_failures_are_indistinguishable(client: TestClient) -> None:
    """三类失败的响应体必须完全相等，不给账号枚举留侧信道。"""
    wrong_password = _login(client, "zhangsan", "wrong-password").json()
    unknown_user = _login(client, "nobody", "St0re#2026").json()
    soft_deleted = _login(client, "lisi", "St0re#2026").json()
    assert wrong_password == unknown_user == soft_deleted
    assert wrong_password["code"] == 40100


def test_login_missing_password_is_validation_error(client: TestClient) -> None:
    """缺字段属于参数校验：40000 / HTTP 400，不进入凭据校验。"""
    resp = client.post(LOGIN_URL, json={"username": "zhangsan"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_me_requires_bearer(client: TestClient) -> None:
    """无 Bearer：401 + 40100，未登录不得拿到用户信息。"""
    resp = client.get(ME_URL)
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


def test_me_returns_profile_and_permissions(client: TestClient) -> None:
    """带 Bearer：返回当前用户信息与权限点列表。"""
    resp = client.get(ME_URL, headers={"Authorization": "Bearer any-token"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert set(data) == {
        "id",
        "username",
        "display_name",
        "store_id",
        "role_codes",
        "permission_codes",
    }
    assert data["id"] == 7
    assert data["username"] == "zhangsan"
    assert data["store_id"] == 3
    assert data["role_codes"] == ["store_manager"]
    assert data["permission_codes"] == ["master:store:read"]
