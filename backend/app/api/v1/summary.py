"""汇总接口（§8.2「汇总分拣」组）。

端点：
- POST /summaries/generate        按 require_date 汇总全部 confirmed 要货单
- GET  /summaries?require_date=&status=   查询汇总单

权限点（§8.3）：summary:generate（ops）/ summary:read（admin, ops）。
数据范围：汇总单是总部视角的单据，不做门店过滤；门店账号无该权限点（40300）。
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query

from app.core.deps import CurrentUser, DbSession, Pagination, require_permission
from app.schema.common import ApiResponse, ok
from app.schema.summary import SummaryGenerate, SummaryOut, SummaryPage, SummaryStatusValue

router = APIRouter()


class SummaryPermission(StrEnum):
    """汇总模块权限点（§8.3），取值即 permission.code。"""

    GENERATE = "summary:generate"
    READ = "summary:read"


def get_summary_service() -> Any:
    """汇总分拣服务提供者：api 经依赖注入取 service，测试可整体替换为 fake。"""
    from app.service import summary_service

    return summary_service


SummaryService = Annotated[Any, Depends(get_summary_service)]

IdempotencyKey = Annotated[
    str | None, Header(alias="Idempotency-Key", max_length=64, description="幂等键，≤64 字符")
]


@router.post("/generate", response_model=ApiResponse[SummaryOut], summary="按配送日汇总要货单")
def generate_summary(
    payload: SummaryGenerate,
    db: DbSession,
    user: CurrentUser,
    service: SummaryService,
    _: Annotated[dict[str, Any], Depends(require_permission(SummaryPermission.GENERATE))],
    idempotency_key: IdempotencyKey = None,
) -> ApiResponse[SummaryOut]:
    """POST /summaries/generate：一配送日一张（uk_req_date），重复触发只落一张。"""
    summary = service.generate_summary(
        db,
        require_date=payload.require_date,
        operator_id=user.get("user_id"),
        idempotency_key=idempotency_key,
    )
    return ok(SummaryOut.model_validate(summary))


@router.get("", response_model=ApiResponse[SummaryPage], summary="查询汇总单")
def list_summaries(
    db: DbSession,
    pagination: Pagination,
    user: CurrentUser,
    service: SummaryService,
    _: Annotated[dict[str, Any], Depends(require_permission(SummaryPermission.READ))],
    require_date: Annotated[date | None, Query(description="需求配送日 YYYY-MM-DD")] = None,
    status_filter: Annotated[
        SummaryStatusValue | None,
        Query(alias="status", description="generated/picking/picked/delivering/done"),
    ] = None,
) -> ApiResponse[SummaryPage]:
    """GET /summaries：按配送日/状态分页查询汇总单（含 SKU 汇总明细）。"""
    result = service.list_summaries(
        db,
        page=pagination.page,
        page_size=pagination.page_size,
        require_date=require_date,
        status=status_filter,
    )
    data = SummaryPage(
        list=[SummaryOut.model_validate(item) for item in result.items],
        total=result.total,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return ok(data)
