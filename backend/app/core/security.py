"""安全能力：密码哈希、JWT 签发与校验、角色判定。

要点（见 docs/05 安全要点）：
- 口令只存哈希，绝不明文落库；
- JWT payload 只放 user_id / role / store_id / exp，不放手机号等敏感信息；
- 角色收敛在服务端做，前端传的 store_id 一律不信任。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# 令牌类型与角色取值
TokenType = Literal["access", "refresh"]
Role = Literal["hq", "store", "driver"]

# bcrypt 自带盐；deprecated="auto" 便于后续平滑更换算法
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class InvalidTokenError(Exception):
    """JWT 校验失败：由 deps 层翻译成 401。"""


# --------------------------------------------------------------------------- 密码
def hash_password(plain_password: str) -> str:
    """明文口令 → 哈希串（入库只存这个）。"""
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验口令；哈希串损坏时返回 False 而不是抛异常。"""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except ValueError:
        return False


# --------------------------------------------------------------------------- JWT
def _encode(payload: dict[str, Any]) -> str:
    """内部：用配置的算法与密钥签名 payload。"""
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(
    subject: str | int,
    *,
    role: Role = "hq",
    store_id: int | None = None,
    expires_minutes: int | None = None,
) -> str:
    """签发 access token。payload 只放最小必要信息。"""
    minutes = expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "store_id": store_id,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
    }
    return _encode(payload)


def create_refresh_token(subject: str | int, *, role: Role = "hq") -> str:
    """签发 refresh token；生产环境中其 jti 需落库以支持撤销。"""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)).timestamp()),
    }
    return _encode(payload)


def decode_token(token: str) -> dict[str, Any]:
    """校验签名与过期时间并返回 payload。

    Raises:
        InvalidTokenError: 签名非法、已过期或格式错误。
    """
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:  # 含 ExpiredSignatureError / JWTClaimsError
        raise InvalidTokenError("令牌无效或已过期") from exc


# --------------------------------------------------------------------------- 角色
def is_hq(role: str) -> bool:
    """总部账号：可跨门店查看与操作。"""
    return role == "hq"


def can_access_store(role: str, token_store_id: int | None, target_store_id: int) -> bool:
    """门店数据越权判定：门店账号只能看自家 store_id。"""
    if is_hq(role):
        return True
    return token_store_id is not None and int(token_store_id) == int(target_store_id)
