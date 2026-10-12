"""认证接口（§8.2）：POST /auth/login、GET /auth/me。

约定：
- 登录失败一律 40100，且 message 不区分「用户不存在 / 密码错误 / 已停用」，防账号枚举；
- 权限点由 deps.get_current_user 统一加载（user→user_role→role_permission→permission）；
- 登录限流复用 core.rate_limit 的 Limiter；未安装 slowapi 时装饰器退化为透传。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.core.deps import AuthService, CurrentUser, DbSession
from app.core.rate_limit import rate_limit
from app.schema.auth import LoginRequest, LoginResponse, MeResponse
from app.schema.common import ApiResponse, ok

router = APIRouter()

# 登录端点限流：防口令爆破。阈值先固定在代码里，后续需要按环境调整时再入 config。
LOGIN_RATE_LIMIT = "10/minute"


@router.post("/login", response_model=ApiResponse[LoginResponse], summary="登录签发 JWT")
@rate_limit(LOGIN_RATE_LIMIT)
def login(
    request: Request,
    payload: LoginRequest,
    db: DbSession,
    service: AuthService,
) -> ApiResponse[LoginResponse]:
    """POST /auth/login：凭据正确则签发 access token；失败统一 40100。"""
    data = service.authenticate(db, payload.username, payload.password)
    if data is None:
        # 防枚举：用户不存在 / 密码错误 / 已停用返回完全一致的响应体
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    return ok(LoginResponse.model_validate(data))


@router.get("/me", response_model=ApiResponse[MeResponse], summary="当前用户信息与权限点")
def me(user: CurrentUser) -> ApiResponse[MeResponse]:
    """GET /auth/me：解析 Bearer（deps.get_current_user）后返回用户与权限点列表。"""
    return ok(
        MeResponse(
            id=int(user["user_id"]),
            username=str(user["username"]),
            display_name=str(user.get("name") or ""),
            store_id=user.get("store_id"),
            role_codes=[str(code) for code in user.get("roles") or ()],
            permission_codes=[str(code) for code in user.get("permissions") or ()],
        )
    )
