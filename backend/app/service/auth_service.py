"""认证服务（§8.2）：登录凭据校验与 JWT 签发。

分层：api 只做 HTTP 翻译（40100 由它抛），本层负责查用户、bcrypt 校验、签发 token；
校验失败统一返回 None，不区分「用户不存在 / 密码错误 / 已停用」，防账号枚举。

安全：jose / passlib 延迟导入，未安装时应用仍可完成编译与路由装配，仅登录不可用
（与 deps.get_current_user 的延迟导入约定一致）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.core.deps import load_user_authorities, load_user_by_username

# RBAC 角色码 → JWT role（§8.1）：admin/ops 视为总部；其余一律非 hq，
# 避免无角色用户凭默认值通过 require_hq。
_HQ_ROLE_CODES = frozenset({"admin", "ops"})


def resolve_token_role(role_codes: Sequence[str]) -> Literal["hq", "store", "driver"]:
    """把 RBAC 角色码收敛成 JWT 里的 role 取值。"""
    if _HQ_ROLE_CODES.intersection(role_codes):
        return "hq"
    if "store_manager" in role_codes:
        return "store"
    if "driver" in role_codes:
        return "driver"
    return "store"


def authenticate(db: Session, username: str, password: str) -> dict[str, Any] | None:
    """校验登录凭据并签发 access token。

    Returns:
        dict: {token, token_type, user:{id, username, display_name, store_id,
              role_codes, permission_codes}}；校验失败返回 None（由 api 转 40100）。
    """
    # 延迟导入：未安装 jose / passlib 时不影响应用装配与其它接口
    from app.core.security import create_access_token, verify_password

    user = load_user_by_username(db, username)
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None

    role_codes, permission_codes = load_user_authorities(db, user.id)
    token = create_access_token(
        user.id, role=resolve_token_role(role_codes), store_id=user.store_id
    )
    return {
        "token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.name,
            "store_id": user.store_id,
            "role_codes": role_codes,
            "permission_codes": permission_codes,
        },
    }
