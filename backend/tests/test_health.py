"""接口测试：健康检查。不连数据库，CI 与本地都能裸跑。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_200() -> None:
    """存活探针：进程活着就该 200。"""
    assert client.get("/api/v1/health").status_code == 200


def test_health_payload_shape() -> None:
    """响应体必须符合统一契约：code=0 且 data.status=ok。"""
    body = client.get("/api/v1/health").json()
    assert body["code"] == 0
    assert body["data"]["status"] == "ok"


def test_openapi_available_in_dev() -> None:
    """开发环境保留交互式文档，三端联调时可用。"""
    assert client.get("/openapi.json").status_code == 200
