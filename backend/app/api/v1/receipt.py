"""签收单接口（§8.2「配送签收」组）。

端点                    用途         默认角色（=权限点集合）
GET /signs/{id}         签收单详情   admin, ops, store_manager(限本店)   sign:read

挂载方式（由 router.py 统一注册）：
    api_router.include_router(receipt.router, prefix="/signs", tags=["配送签收"])
本模块服务的写入口是 POST /deliveries/{id}/sign（签名与配送单同前缀，故落在 delivery.py）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path

from app.api.v1.delivery import actor_from_user
from app.core.deps import CurrentUser, DbSession, PermissionCode, require_permission
from app.schema.common import ApiResponse, ok
from app.schema.delivery import SignOut

router = APIRouter()


def get_receipt_service() -> Any:
    """签收查询服务提供者（与配送同属 delivery_service，测试可替换为 fake）。"""
    from app.service import delivery_service

    return delivery_service


ReceiptService = Annotated[Any, Depends(get_receipt_service)]


@router.get("/{sign_id}", response_model=ApiResponse[SignOut], summary="签收单详情")
def get_sign(
    sign_id: Annotated[int, Path(ge=1)],
    db: DbSession,
    user: CurrentUser,
    service: ReceiptService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.SIGN_READ))],
) -> ApiResponse[SignOut]:
    """GET /signs/{id}：签收单 + 明细（含差异生成列）+ 关联配送单号；门店账号限本店。"""
    detail = service.get_sign(db, sign_id, actor=actor_from_user(user))
    return ok(
        SignOut.build(detail.sign, items=detail.items, delivery_no=detail.delivery.delivery_no)
    )
