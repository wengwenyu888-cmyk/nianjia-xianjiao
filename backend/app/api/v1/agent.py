"""智能体接口（§8.2「智能体」组，规则版 rule-v1，不接真 LLM）。

端点：
- POST /agent/order-suggestions     生成要货建议（按店按日），快照落 agent_suggestion(pending)
- GET  /agent/order-suggestions/{id}         查看建议快照与依据
- POST /agent/order-suggestions/{id}/apply   应用建议→生成 draft 要货单（仍须店长 confirm）
- POST /agent/pick-plan                      配货/分拣批次计划（FIFO 预演，只读），落 pick_plan 快照

权限点（§8.3）：agent:suggest / agent:read / agent:apply / agent:pick_plan。
「只建议不落账」：本组端点不产生有效单据，apply 只生成 draft，生效仍走 order:confirm。
数据范围（§8.1）：门店账号只能生成/查看/采纳本店建议，越权 40300。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Path

from app.core.deps import CurrentUser, DbSession, PermissionCode, require_permission
from app.schema.agent import (
    PickPlanOut,
    PickPlanRequest,
    SuggestionGenerate,
    SuggestionOut,
)
from app.schema.common import ApiResponse, ok
from app.schema.order import OrderOut

router = APIRouter()


def get_agent_service() -> Any:
    """智能体服务提供者：api 经依赖注入取 service，测试可整体替换为 fake。"""
    from app.service import agent_service

    return agent_service


AgentService = Annotated[Any, Depends(get_agent_service)]

IdempotencyKey = Annotated[
    str | None, Header(alias="Idempotency-Key", max_length=64, description="幂等键，≤64 字符")
]


@router.post(
    "/order-suggestions",
    response_model=ApiResponse[SuggestionOut],
    summary="生成要货建议(按店按日)",
)
def create_order_suggestions(
    payload: SuggestionGenerate,
    db: DbSession,
    user: CurrentUser,
    service: AgentService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.AGENT_SUGGEST))],
    idempotency_key: IdempotencyKey = None,
) -> ApiResponse[SuggestionOut]:
    """POST /agent/order-suggestions：规则版建议（近 7 天均值 × 星期系数 + 库存/效期校正）。"""
    suggestion = service.generate_order_suggestions(
        db,
        payload,
        store_id_scope=user.get("store_id"),
        operator_id=user.get("user_id"),
        idempotency_key=idempotency_key,
    )
    return ok(SuggestionOut.model_validate(suggestion))


@router.get(
    "/order-suggestions/{suggestion_id}",
    response_model=ApiResponse[SuggestionOut],
    summary="查看建议快照与依据",
)
def get_order_suggestion(
    suggestion_id: Annotated[int, Path(ge=1)],
    db: DbSession,
    user: CurrentUser,
    service: AgentService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.AGENT_READ))],
) -> ApiResponse[SuggestionOut]:
    """GET /agent/order-suggestions/{id}：读 agent_suggestion.payload（生成当时的依据快照）。"""
    suggestion = service.get_suggestion(db, suggestion_id, store_id_scope=user.get("store_id"))
    return ok(SuggestionOut.model_validate(suggestion))


@router.post(
    "/order-suggestions/{suggestion_id}/apply",
    response_model=ApiResponse[OrderOut],
    summary="应用建议(生成 draft 要货单)",
)
def apply_order_suggestion(
    suggestion_id: Annotated[int, Path(ge=1)],
    db: DbSession,
    user: CurrentUser,
    service: AgentService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.AGENT_APPLY))],
    idempotency_key: IdempotencyKey = None,
) -> ApiResponse[OrderOut]:
    """POST /agent/order-suggestions/{id}/apply：只生成 draft 要货单，须店长 confirm 才生效。"""
    order = service.apply_suggestion(
        db,
        suggestion_id,
        store_id_scope=user.get("store_id"),
        operator_id=user.get("user_id"),
        idempotency_key=idempotency_key,
    )
    return ok(OrderOut.model_validate(order))


@router.post(
    "/pick-plan", response_model=ApiResponse[PickPlanOut], summary="配货/分拣批次计划(FIFO 预演)"
)
def create_pick_plan(
    payload: PickPlanRequest,
    db: DbSession,
    user: CurrentUser,
    service: AgentService,
    _: Annotated[dict[str, Any], Depends(require_permission(PermissionCode.AGENT_PICK_PLAN))],
    idempotency_key: IdempotencyKey = None,
) -> ApiResponse[PickPlanOut]:
    """POST /agent/pick-plan：只读 FIFO 预演（不锁行/不扣结存/不写流水），落 pick_plan 快照。"""
    suggestion = service.build_pick_plan(
        db, payload, operator_id=user.get("user_id"), idempotency_key=idempotency_key
    )
    plan = PickPlanOut.model_validate({**suggestion.payload, "suggestion_id": suggestion.id})
    return ok(plan)
