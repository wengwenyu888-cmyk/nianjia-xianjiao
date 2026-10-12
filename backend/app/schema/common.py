"""通用数据契约：统一响应体、分页、业务枚举。

约定：对外返回一律用 schema，禁止直接返回 ORM 对象（防字段泄露与 N+1）。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")
# 注解别名：Page 的字段名就叫 list，会遮蔽内建 list，故这里先把 list[T] 求值成别名。
PageList = list[T]


class ApiResponse[T](BaseModel):
    """统一响应体：成功与失败都返回这个形状。

    code 约定：0 成功；非 0 为业务错误码，如 40400 对应 404。
    """

    code: int = Field(default=0, description="0 表示成功，非 0 为业务错误码")
    message: str = Field(default="ok", description="提示信息")
    data: T | None = Field(default=None, description="业务数据")

    model_config = ConfigDict(
        json_schema_extra={"example": {"code": 0, "message": "ok", "data": None}}
    )


def ok[T](data: T | None = None, message: str = "ok") -> ApiResponse[T]:
    """成功响应快捷构造。"""
    return ApiResponse[T](code=0, message=message, data=data)


class Page[T](BaseModel):
    """分页响应体（对齐 docs/02 §8.1）：list/total/page/page_size 平铺。"""

    list: PageList = Field(default_factory=list, description="当前页数据")
    total: int = Field(ge=0, description="总条数")
    page: int = Field(ge=1, description="当前页码")
    page_size: int = Field(ge=1, description="每页条数")

    @classmethod
    def build(cls, items: PageList, *, page: int, page_size: int, total: int) -> Page[T]:
        """按总数与页大小组装分页结果。"""
        return cls(list=items, total=total, page=page, page_size=page_size)


class OrderStatus(StrEnum):
    """要货单状态机（对齐 docs/02 v0.3.1 §7 order_head）：draft→confirmed→merged→cancelled。

    状态流转只能在 service 层做，前端不可直接改状态。
    其他单据的状态机值域各自不同（summary/pick/delivery/sign/loss/reconcile），
    在各自模块的 schema 中按 DDL 定义，不放进本通用枚举。
    """

    DRAFT = "draft"  # 草稿（智能体建议只能生成到此状态）
    CONFIRMED = "confirmed"  # 店长确认生效
    MERGED = "merged"  # 已汇总
    CANCELLED = "cancelled"  # 已取消


class RoleCode(StrEnum):
    """账号角色（对齐 docs/02 v0.3.1 §8.1 四角色）。门店账号只能看自家 store_id 的数据。"""

    ADMIN = "admin"
    OPS = "ops"
    DRIVER = "driver"
    STORE_MANAGER = "store_manager"


class SimpleResult(BaseModel):
    """只回一个布尔或 ID 的简单结果。"""

    success: bool = True
    id: int | None = None
    detail: dict[str, Any] | None = None
