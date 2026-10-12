"""认证数据契约（§8.2）：登录请求/响应与当前用户信息。

约定：只暴露 id / username / display_name / store_id / 角色码 / 权限点码，
password_hash 等敏感字段绝不进 schema（见安全要点「口令只存哈希」）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    """POST /auth/login 请求体。"""

    username: str = Field(min_length=1, max_length=32, description="登录名")
    password: str = Field(min_length=1, max_length=128, description="明文口令，仅本次校验使用")


class UserInfo(BaseModel):
    """对外用户信息：角色与权限点并集，供前端做菜单/按钮渲染。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    store_id: int | None = Field(default=None, description="NULL=总部用户;门店用户挂本店ID")
    role_codes: list[str] = Field(default_factory=list, description="角色码，如 store_manager")
    permission_codes: list[str] = Field(default_factory=list, description="权限点码并集")


class LoginResponse(BaseModel):
    """POST /auth/login 响应：签发令牌 + 当前用户。"""

    token: str = Field(description="access token")
    token_type: str = Field(default="bearer", description="固定 bearer（§8.1）")
    user: UserInfo


class MeResponse(UserInfo):
    """GET /auth/me 响应：当前用户信息与权限点（复用 UserInfo 字段）。"""
