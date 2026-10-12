"""主数据-价目接口（§8.2）。

端点：POST /prices（新增价目）、GET /prices?sku_id=&date=（查历史当时价）。
权限点：master:price:write（admin）/ master:price:read（admin, ops）。
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query

from app.core.deps import (
    CurrentUser,
    DbSession,
    MasterService,
    Pagination,
    PermissionCode,
    require_permission,
)
from app.schema.common import ApiResponse, ok
from app.schema.store import PriceCreate, PriceOut, PricePage

router = APIRouter()

IdempotencyKey = Annotated[
    str | None, Header(alias="Idempotency-Key", max_length=64, description="幂等键，≤64 字符")
]


@router.post("", response_model=ApiResponse[PriceOut], summary="新增价目(生效区间)")
def create_price(
    payload: PriceCreate,
    db: DbSession,
    user: CurrentUser,
    service: MasterService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.PRICE_WRITE))],
    idempotency_key: IdempotencyKey = None,
) -> ApiResponse[PriceOut]:
    """POST /prices：价格带生效区间、只增不改；同 SKU 同类型同生效日重复提交返回首次结果。"""
    price = service.create_price(
        db, payload, operator_id=user.get("user_id"), idempotency_key=idempotency_key
    )
    return ok(PriceOut.model_validate(price))


@router.get("", response_model=ApiResponse[PricePage], summary="查历史当时价")
def list_prices(
    db: DbSession,
    pagination: Pagination,
    user: CurrentUser,
    service: MasterService,
    sku_id: Annotated[int, Query(gt=0, description="SKU id")],
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.PRICE_READ))],
    on_date: Annotated[
        date | None, Query(alias="date", description="YYYY-MM-DD，命中生效区间")
    ] = None,
) -> ApiResponse[PricePage]:
    """GET /prices?sku_id=&date=：date 缺省时不限生效区间，返回全部历史价。"""
    result = service.list_prices(
        db,
        sku_id=sku_id,
        on_date=on_date,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    data = PricePage(
        list=[PriceOut.model_validate(item) for item in result.items],
        total=result.total,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return ok(data)
