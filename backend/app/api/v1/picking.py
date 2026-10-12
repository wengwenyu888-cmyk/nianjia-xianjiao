"""分拣接口（§8.2「汇总分拣」组）。

端点：
- POST /picks                 按门店生成分拣单（锁批次扣总部仓库存，事务）
- POST /picks/{id}/complete   分拣完成

权限点（§8.3）：pick:create / pick:complete（默认角色 ops）。
库存事务：扣减 batch_stock 与写 batch_flow(pick_sub) 在同一事务内完成；
库存不足抛 40900 并整体回滚（扣减失败不入配送）。
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Path, Query

from app.core.deps import CurrentUser, DbSession, Pagination, PermissionCode, require_permission
from app.schema.common import ApiResponse, ok
from app.schema.summary import PickCreate, PickOut, PickPage

router = APIRouter()


def get_summary_service() -> Any:
    """分拣服务提供者（分拣隶属汇总分拣服务模块）。"""
    from app.service import summary_service

    return summary_service


SummaryService = Annotated[Any, Depends(get_summary_service)]

IdempotencyKey = Annotated[
    str | None, Header(alias="Idempotency-Key", max_length=64, description="幂等键，≤64 字符")
]


@router.post("", response_model=ApiResponse[PickOut], summary="按门店生成分拣单")
def create_pick(
    payload: PickCreate,
    db: DbSession,
    user: CurrentUser,
    service: SummaryService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.PICK_CREATE))],
    idempotency_key: IdempotencyKey = None,
) -> ApiResponse[PickOut]:
    """POST /picks：FIFO 锁定并扣减总部仓批次结存，同事务写批次流水，落批次明细。"""
    pick = service.create_pick(
        db, payload, operator_id=user.get("user_id"), idempotency_key=idempotency_key
    )
    return ok(PickOut.model_validate(pick))


@router.get("", response_model=ApiResponse[PickPage], summary="查询分拣单")
def list_picks(
    db: DbSession,
    pagination: Pagination,
    user: CurrentUser,
    service: SummaryService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.PICK_CREATE))],
    require_date: Annotated[date | None, Query(description="需求配送日 YYYY-MM-DD")] = None,
    summary_id: Annotated[int | None, Query(ge=1, description="汇总单 id")] = None,
    store_id: Annotated[int | None, Query(ge=1, description="门店 id")] = None,
    status_filter: Annotated[
        str | None, Query(alias="status", description="created/picking/done/cancelled")
    ] = None,
) -> ApiResponse[PickPage]:
    """GET /picks：按配送日/汇总单/门店/状态分页查询分拣单（含批次明细）。

    权限说明：§8.3 未单列 pick:read，读列表沿用 pick:create 的持有者（ops/admin）。
    """
    result = service.list_picks(
        db,
        page=pagination.page,
        page_size=pagination.page_size,
        require_date=require_date,
        summary_id=summary_id,
        store_id=store_id,
        status=status_filter,
    )
    data = PickPage(
        list=[PickOut.model_validate(item) for item in result.items],
        total=result.total,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return ok(data)


@router.post("/{pick_id}/complete", response_model=ApiResponse[PickOut], summary="分拣完成")
def complete_pick(
    pick_id: Annotated[int, Path(ge=1)],
    db: DbSession,
    user: CurrentUser,
    service: SummaryService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.PICK_COMPLETE))],
    idempotency_key: IdempotencyKey = None,
) -> ApiResponse[PickOut]:
    """POST /picks/{id}/complete：created/picking→done；全部门店完成后汇总单→picked。"""
    pick = service.complete_pick(db, pick_id, operator_id=user.get("user_id"))
    return ok(PickOut.model_validate(pick))
