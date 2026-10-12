"""智能体建议服务（§7.3 agent_suggestion + §8.2「智能体」组端点）。

规则版（rule-v1，不接真 LLM）：
- 要货建议 = 该店近 7 天该 SKU 已确认/已汇总要货量的日均值 × 星期系数，
  再结合总部仓未过期可发量与批次效期做下调与提示；依据快照 JSON 落 agent_suggestion.payload。
- 配货计划 = 按 require_date 对全部门店需求做 FIFO 批次预演（只读：不锁行、不扣结存、不写流水）。

「只建议不落账」铁律：
- 生成建议本身不产生任何有效单据，只写建议快照行（apply_status=pending）；
- apply_suggestion 只生成 draft 要货单（source=agent、agent_suggestion_id 回指），
  须店长走 order:confirm 才生效；
- pick_plan 的 apply_status 保持 pending（只读预演，不供采纳）。

幂等（§8.1）：uk_idem(idempotency_key, deleted_at)；apply 以「建议状态 + 派生键
agent-apply-{id}」兜底，重复 apply 返回首次生成的 draft 要货单。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import (
    BusinessError,
    ConflictError,
    PermissionDeniedError,
)
from app.model.inventory import BatchStock
from app.model.order import AgentSuggestion, OrderHead, OrderItem
from app.model.store import Sku, Store
from app.schema.agent import PickPlanRequest, SuggestionGenerate
from app.schema.order import OrderCreate, OrderItemIn
from app.service import order_service
from app.service.order_service import quantize_qty
from app.service.store_service import (
    PageResult,
    _find_one,
    _insert_idempotent,
    _load_or_404,
    _not_deleted,
    _page_query,
    fingerprint_payload,
)

# --------------------------------------------------------------------------- 常量
POLICY_VERSION = "rule-v1"
# 总部仓 store_id（§7.2：0=总部仓）
WAREHOUSE_STORE_ID = 0
# 回看窗口：近 7 天（不含 require_date 当天）
LOOKBACK_DAYS = 7
# 星期系数（周一..周日）：周末堂食客流高，要货量上浮；规则版可整体替换为 LLM 版本
WEEKDAY_FACTORS: tuple[Decimal, ...] = (
    Decimal("1.00"),
    Decimal("1.00"),
    Decimal("1.00"),
    Decimal("1.00"),
    Decimal("1.05"),
    Decimal("1.20"),
    Decimal("1.15"),
)
# 临期提示阈值：24 小时内到期
NEAR_EXPIRE_HOURS = 24
SUGGESTION_TYPE_ORDER = "order_suggest"
SUGGESTION_TYPE_PICK_PLAN = "pick_plan"
APPLY_STATUSES: tuple[str, ...] = ("pending", "applied", "rejected", "expired")


def _to_decimal(value: Any) -> Decimal | None:
    """宽松解析快照里的数量字段；坏数据返回 None（不把脏数据带进单据）。"""
    try:
        return quantize_qty(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _snapshot_stock(
    db: Session, sku_ids: Sequence[int], *, now: datetime
) -> dict[int, dict[str, Any]]:
    """总部仓未过期可发量 + 最近效期（SUM/MIN 聚合，一次查询覆盖全部 SKU）。"""
    if not sku_ids:
        return {}
    rows = db.execute(
        select(
            BatchStock.sku_id,
            func.sum(BatchStock.qty_base).label("available_qty_base"),
            func.min(BatchStock.expire_at).label("nearest_expire_at"),
        )
        .where(
            _not_deleted(BatchStock),
            BatchStock.store_id == WAREHOUSE_STORE_ID,
            BatchStock.sku_id.in_([int(sku_id) for sku_id in sku_ids]),
            BatchStock.qty_base > 0,
            BatchStock.expire_at > now,
        )
        .group_by(BatchStock.sku_id)
    ).all()
    return {
        int(row.sku_id): {
            "available": quantize_qty(row.available_qty_base or 0),
            "nearest_expire_at": row.nearest_expire_at,
        }
        for row in rows
    }


# --------------------------------------------------------------------------- 要货建议
def _build_order_suggest_payload(db: Session, store_id: int, require_date: date) -> dict[str, Any]:
    """规则版建议依据快照：销量均值 × 星期系数 → 库存/效期校正 → JSON 可序列化明细。"""
    now = datetime.now()
    window_start = require_date - timedelta(days=LOOKBACK_DAYS)
    history = list(
        db.execute(
            select(
                OrderItem.sku_id,
                func.sum(OrderItem.qty_base).label("total_qty_base"),
                func.count(func.distinct(OrderHead.require_date)).label("observed_days"),
            )
            .join(OrderHead, OrderHead.id == OrderItem.order_id)
            .where(
                _not_deleted(OrderHead),
                OrderHead.store_id == int(store_id),
                OrderHead.status.in_(("confirmed", "merged")),
                OrderHead.require_date >= window_start,
                OrderHead.require_date < require_date,
            )
            .group_by(OrderItem.sku_id)
            .order_by(OrderItem.sku_id)
        ).all()
    )
    sku_ids = [int(row.sku_id) for row in history]
    skus = {
        int(sku.id): sku
        for sku in db.scalars(select(Sku).where(Sku.id.in_(sku_ids), _not_deleted(Sku))).all()
    }
    stock = _snapshot_stock(db, sku_ids, now=now)
    factor = WEEKDAY_FACTORS[require_date.weekday()]

    items: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    warnings: list[str] = []
    for row in history:
        sku = skus.get(int(row.sku_id))
        if sku is None:
            continue
        total_qty = quantize_qty(row.total_qty_base)
        observed_days = int(row.observed_days or 0)
        avg_qty = quantize_qty(total_qty / Decimal(LOOKBACK_DAYS))
        weekday_qty = quantize_qty(avg_qty * factor)
        stock_row = stock.get(int(sku.id), {})
        available = quantize_qty(stock_row.get("available", Decimal("0.000")))
        nearest_expire = stock_row.get("nearest_expire_at")
        factor_sku = Decimal(sku.convert_factor if sku.convert_factor else 1)

        suggest = weekday_qty
        flags: list[str] = []
        if available <= 0:
            suggest = Decimal("0.000")
            flags.append("总部仓无未过期可用批次，本次不建议该 SKU")
        elif available < weekday_qty:
            suggest = available
            flags.append("总部仓库存不足，建议量下调至可满足量")
        if nearest_expire is not None and nearest_expire <= now + timedelta(
            hours=NEAR_EXPIRE_HOURS
        ):
            flags.append("存在 24 小时内到期批次，分拣请按 FIFO 先出")

        entry = {
            "sku_id": int(sku.id),
            "sku_no": sku.sku_no,
            "sku_name": sku.name,
            "unit": sku.unit,
            "base_unit": sku.base_unit,
            "convert_factor": str(factor_sku),
            "observed_days": observed_days,
            "history_qty_base": str(total_qty),
            "avg_qty_base": str(avg_qty),
            "weekday_factor": str(factor),
            "weekday_qty_base": str(weekday_qty),
            "suggest_qty_base": str(suggest),
            "suggest_qty_unit": str(quantize_qty(suggest / factor_sku)),
            "hq_available_qty_base": str(available),
            "nearest_expire_at": nearest_expire.isoformat(timespec="seconds")
            if nearest_expire
            else None,
            "shelf_life_hours": int(sku.shelf_life_hours),
            "flags": flags,
            "reason": "近 7 天日均要货量 × 星期系数，再按总部仓未过期可发量校正",
        }
        if suggest <= 0:
            skipped.append(entry)
        else:
            items.append(entry)

    if not history:
        warnings.append("该店近 7 天没有已确认/已汇总的要货记录，建议明细为空（需人工下单）")
    if skipped:
        warnings.append(f"{len(skipped)} 个 SKU 因总部仓无可发量未进入建议明细")

    suggest_total = sum((Decimal(item["suggest_qty_base"]) for item in items), Decimal("0.000"))
    return {
        "policy": POLICY_VERSION,
        "generated_at": now.isoformat(timespec="seconds"),
        "store_id": int(store_id),
        "require_date": require_date.isoformat(),
        "lookback_days": LOOKBACK_DAYS,
        "weekday_factor": str(factor),
        "basis": "近 7 天该 SKU 要货量日均值 × 星期系数，结合总部仓库存与批次效期校正",
        "items": items,
        "skipped": skipped,
        "warnings": warnings,
        "totals": {
            "item_count": len(items),
            "suggest_qty_base": str(quantize_qty(suggest_total)),
        },
    }


def generate_order_suggestions(
    db: Session,
    payload: SuggestionGenerate,
    *,
    store_id_scope: int | None = None,
    operator_id: int | None = None,
    idempotency_key: str | None = None,
) -> AgentSuggestion:
    """生成要货建议快照（apply_status=pending，只建议不落账）。

    门店账号只能为本店生成（越权 40300）；快照可多轮生成，仅幂等键去重。
    """
    store_id = int(payload.store_id) if payload.store_id is not None else store_id_scope
    if store_id is None:
        raise BusinessError("生成要货建议时必须指定 store_id")
    if store_id_scope is not None and store_id != int(store_id_scope):
        raise PermissionDeniedError("门店账号只能为本店生成要货建议")
    _load_or_404(db, Store, store_id, "门店")

    snapshot = _build_order_suggest_payload(db, store_id, payload.require_date)
    request_fp = fingerprint_payload(
        {"store_id": store_id, "require_date": payload.require_date, "type": SUGGESTION_TYPE_ORDER}
    )
    return _insert_idempotent(
        db,
        build=lambda: AgentSuggestion(
            suggestion_type=SUGGESTION_TYPE_ORDER,
            store_id=store_id,
            require_date=payload.require_date,
            payload=snapshot,
            apply_status="pending",
            model=POLICY_VERSION,
            idempotency_key=idempotency_key,
            created_by=operator_id,
            updated_by=operator_id,
        ),
        find_existing=lambda: (
            _find_one(db, AgentSuggestion, AgentSuggestion.idempotency_key == idempotency_key)
            if idempotency_key
            else None
        ),
        request_fingerprint=request_fp,
        existing_fingerprint=lambda entity: fingerprint_payload(
            {
                "store_id": int(entity.store_id),
                "require_date": entity.require_date,
                "type": entity.suggestion_type,
            }
        ),
        conflict_message="幂等键重复且建议请求与首次提交不一致",
    )


def get_suggestion(
    db: Session, suggestion_id: int, *, store_id_scope: int | None = None
) -> AgentSuggestion:
    """按 id 取建议快照；不存在 40400，门店账号看非本店建议 40300。"""
    suggestion = _load_or_404(db, AgentSuggestion, suggestion_id, "智能体建议")
    if store_id_scope is not None and int(suggestion.store_id) != int(store_id_scope):
        raise PermissionDeniedError("门店账号只能查看本店建议")
    return suggestion


def list_suggestions(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    store_id: int | None = None,
    require_date: date | None = None,
    suggestion_type: str | None = None,
    apply_status: str | None = None,
    store_id_scope: int | None = None,
) -> PageResult[AgentSuggestion]:
    """建议快照分页查询（§8.2 未开放列表端点，契约先行，供治理看板复用）。"""
    if store_id_scope is not None:
        if store_id is not None and int(store_id) != int(store_id_scope):
            raise PermissionDeniedError("门店账号只能查询本店建议")
        store_id = int(store_id_scope)
    conditions: list[Any] = [_not_deleted(AgentSuggestion)]
    if store_id is not None:
        conditions.append(AgentSuggestion.store_id == int(store_id))
    if require_date is not None:
        conditions.append(AgentSuggestion.require_date == require_date)
    if suggestion_type is not None:
        if suggestion_type not in (SUGGESTION_TYPE_ORDER, SUGGESTION_TYPE_PICK_PLAN):
            raise BusinessError(f"建议类型非法：{suggestion_type}")
        conditions.append(AgentSuggestion.suggestion_type == suggestion_type)
    if apply_status is not None:
        if apply_status not in APPLY_STATUSES:
            raise BusinessError(f"建议应用状态非法：{apply_status}")
        conditions.append(AgentSuggestion.apply_status == apply_status)
    return _page_query(
        db,
        AgentSuggestion,
        conditions,
        page=page,
        page_size=page_size,
        order_by=(AgentSuggestion.id.desc(),),
    )


def _order_items_from_snapshot(payload: dict[str, Any]) -> list[OrderItemIn]:
    """把建议快照明细转成要货明细（按 SKU 去重，坏行跳过而非带脏数据入单）。"""
    items: list[OrderItemIn] = []
    seen: set[int] = set()
    for raw in payload.get("items") or ():
        if not isinstance(raw, dict):
            continue
        try:
            sku_id = int(raw.get("sku_id") or 0)
        except (TypeError, ValueError):
            continue
        qty_unit = _to_decimal(raw.get("suggest_qty_unit"))
        if sku_id <= 0 or sku_id in seen or qty_unit is None or qty_unit <= 0:
            continue
        seen.add(sku_id)
        items.append(OrderItemIn(sku_id=sku_id, qty_unit=qty_unit, unit=raw.get("unit") or None))
    return items


def apply_suggestion(
    db: Session,
    suggestion_id: int,
    *,
    store_id_scope: int | None = None,
    operator_id: int | None = None,
    idempotency_key: str | None = None,
) -> OrderHead:
    """采纳建议 → 生成 draft 要货单（仍须店长 order:confirm 才生效）。

    重复 apply 返回首次生成的 draft 单；已 rejected/expired 的建议 40900；
    行锁 + 状态判定防两个店长并发采纳同一建议。
    """
    suggestion = _load_or_404(db, AgentSuggestion, suggestion_id, "智能体建议")
    if suggestion.suggestion_type != SUGGESTION_TYPE_ORDER:
        raise ConflictError("仅要货建议（order_suggest）可被采纳")
    if store_id_scope is not None and int(suggestion.store_id) != int(store_id_scope):
        raise PermissionDeniedError("门店账号只能采纳本店建议")
    if suggestion.apply_status == "applied" and suggestion.order_id:
        order = _load_or_404(db, OrderHead, int(suggestion.order_id), "要货单")
        order_service.attach_items(db, [order])
        return order
    if suggestion.apply_status != "pending":
        raise ConflictError(f"建议当前状态为 {suggestion.apply_status}，不能采纳")
    if suggestion.require_date is None:
        raise ConflictError("建议缺少需求配送日，不能采纳")

    # 行锁：并发 apply 串行化，后到者读到的已是 applied
    locked = db.scalar(
        select(AgentSuggestion).where(AgentSuggestion.id == int(suggestion.id)).with_for_update()
    )
    if locked is not None:
        suggestion = locked
        if suggestion.apply_status == "applied" and suggestion.order_id:
            order = _load_or_404(db, OrderHead, int(suggestion.order_id), "要货单")
            order_service.attach_items(db, [order])
            return order
        if suggestion.apply_status != "pending":
            raise ConflictError(f"建议当前状态为 {suggestion.apply_status}，不能采纳")

    order_items = _order_items_from_snapshot(suggestion.payload or {})
    if not order_items:
        raise ConflictError("建议没有可采纳的明细")

    order = order_service.create_order(
        db,
        OrderCreate(
            store_id=int(suggestion.store_id),
            require_date=suggestion.require_date,
            items=order_items,
        ),
        store_id_scope=None,
        operator_id=operator_id,
        idempotency_key=idempotency_key or f"agent-apply-{int(suggestion.id)}",
        source="agent",
        agent_suggestion_id=int(suggestion.id),
    )
    suggestion.apply_status = "applied"
    suggestion.applied_by = operator_id
    suggestion.applied_at = datetime.now()
    suggestion.order_id = int(order.id)
    suggestion.version = int(suggestion.version or 0) + 1
    suggestion.updated_by = operator_id
    db.flush()
    return order


# --------------------------------------------------------------------------- 配货计划（只读预演）
def _simulate_fifo(db: Session, require_date: date) -> dict[str, Any]:
    """FIFO 批次预演（只读）：不写结存、不写流水、不加行锁。

    预演口径：按 (store_id, sku_id) 升序依次占用总部仓批次（expire_at 升序），
    门店之间互相竞争同一批批次；真实分拣时以 SELECT ... FOR UPDATE 的实际结果为准。
    """
    now = datetime.now()
    demand = list(
        db.execute(
            select(
                OrderHead.store_id,
                OrderItem.sku_id,
                func.sum(OrderItem.qty_base).label("required_qty_base"),
            )
            .join(OrderItem, OrderItem.order_id == OrderHead.id)
            .where(
                _not_deleted(OrderHead),
                OrderHead.require_date == require_date,
                OrderHead.status.in_(("confirmed", "merged")),
            )
            .group_by(OrderHead.store_id, OrderItem.sku_id)
            .order_by(OrderHead.store_id, OrderItem.sku_id)
        ).all()
    )
    warnings: list[str] = []
    if not demand:
        warnings.append("该配送日没有已确认/已汇总的要货单，无可预演的分拣批次")
        return {
            "policy": POLICY_VERSION,
            "generated_at": now.isoformat(timespec="seconds"),
            "require_date": require_date.isoformat(),
            "tasks": [],
            "warnings": warnings,
            "total_required_qty_base": "0.000",
            "total_shortage_qty_base": "0.000",
        }

    sku_ids = sorted({int(row.sku_id) for row in demand})
    batches = list(
        db.scalars(
            select(BatchStock)
            .where(
                _not_deleted(BatchStock),
                BatchStock.store_id == WAREHOUSE_STORE_ID,
                BatchStock.sku_id.in_(sku_ids),
                BatchStock.qty_base > 0,
            )
            .order_by(BatchStock.expire_at.asc(), BatchStock.id.asc())
        ).all()
    )
    queue: dict[int, list[BatchStock]] = {}
    remaining: dict[tuple[int, str], Decimal] = {}
    for batch in batches:
        queue.setdefault(int(batch.sku_id), []).append(batch)
        remaining[(int(batch.sku_id), batch.batch_no)] = quantize_qty(batch.qty_base)

    tasks: list[dict[str, Any]] = []
    for row in demand:
        sku_id = int(row.sku_id)
        need = quantize_qty(row.required_qty_base)
        required = need
        allocated = Decimal("0.000")
        picked: list[dict[str, Any]] = []
        flags: list[str] = []
        for batch in queue.get(sku_id, []):
            if need <= 0:
                break
            key = (sku_id, batch.batch_no)
            available = remaining.get(key, Decimal("0.000"))
            if available <= 0:
                continue
            take = available if available < need else need
            remaining[key] = available - take
            need -= take
            allocated += take
            if batch.expire_at is not None and batch.expire_at <= now + timedelta(
                hours=NEAR_EXPIRE_HOURS
            ):
                flags.append("命中 24 小时内到期批次，需优先出库")
            picked.append(
                {
                    "batch_no": batch.batch_no,
                    "qty_base": str(take),
                    "expire_at": batch.expire_at.isoformat(timespec="seconds")
                    if batch.expire_at
                    else None,
                    "produced_at": batch.produced_at.isoformat() if batch.produced_at else None,
                }
            )
        if need > 0:
            flags.append(f"总部仓预演缺口 {need}，需补货或拆分配送")
            warnings.append(f"门店 {row.store_id} 的 SKU {sku_id} 预演缺口 {need}")
        tasks.append(
            {
                "store_id": int(row.store_id),
                "sku_id": sku_id,
                "required_qty_base": str(required),
                "allocated_qty_base": str(allocated),
                "shortage_qty_base": str(need),
                "batches": picked,
                "flags": flags,
            }
        )

    required_total = sum((Decimal(task["required_qty_base"]) for task in tasks), Decimal("0.000"))
    shortage_total = sum((Decimal(task["shortage_qty_base"]) for task in tasks), Decimal("0.000"))
    return {
        "policy": POLICY_VERSION,
        "generated_at": now.isoformat(timespec="seconds"),
        "require_date": require_date.isoformat(),
        "tasks": tasks,
        "warnings": warnings,
        "total_required_qty_base": str(quantize_qty(required_total)),
        "total_shortage_qty_base": str(quantize_qty(shortage_total)),
    }


def build_pick_plan(
    db: Session,
    payload: PickPlanRequest,
    *,
    operator_id: int | None = None,
    idempotency_key: str | None = None,
) -> AgentSuggestion:
    """配货/分拣批次计划（FIFO 预演，只读）：仅落一条 pick_plan 建议快照。"""
    plan = _simulate_fifo(db, payload.require_date)
    return _insert_idempotent(
        db,
        build=lambda: AgentSuggestion(
            suggestion_type=SUGGESTION_TYPE_PICK_PLAN,
            store_id=WAREHOUSE_STORE_ID,
            require_date=payload.require_date,
            payload=plan,
            apply_status="pending",
            model=POLICY_VERSION,
            idempotency_key=idempotency_key,
            created_by=operator_id,
            updated_by=operator_id,
        ),
        find_existing=lambda: (
            _find_one(db, AgentSuggestion, AgentSuggestion.idempotency_key == idempotency_key)
            if idempotency_key
            else None
        ),
        request_fingerprint=fingerprint_payload(
            {
                "type": SUGGESTION_TYPE_PICK_PLAN,
                "store_id": WAREHOUSE_STORE_ID,
                "require_date": payload.require_date,
            }
        ),
        existing_fingerprint=lambda entity: fingerprint_payload(
            {
                "type": entity.suggestion_type,
                "store_id": int(entity.store_id),
                "require_date": entity.require_date,
            }
        ),
        conflict_message="幂等键重复且配货计划请求与首次提交不一致",
    )


__all__: list[str] = [
    "APPLY_STATUSES",
    "NEAR_EXPIRE_HOURS",
    "POLICY_VERSION",
    "SUGGESTION_TYPE_ORDER",
    "SUGGESTION_TYPE_PICK_PLAN",
    "WEEKDAY_FACTORS",
    "apply_suggestion",
    "build_pick_plan",
    "generate_order_suggestions",
    "get_suggestion",
    "list_suggestions",
]
