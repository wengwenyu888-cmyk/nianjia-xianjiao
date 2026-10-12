"""汇总与分拣服务（§7.3 / §7.4 模型 + §8.2「汇总分拣」组端点）。

职责分离：「汇总看量、分拣落批次」——汇总只到 SKU 维度（summary_item），
批次分配只发生在分拣环节（pick_item），按 expire_at 升序 FIFO。

状态机（只在 service 层流转）：
  summary: generated→picking→picked→delivering→done
           本模块负责 generated→picking（生成首张分拣单）、picking→picked（分拣全部完成）；
           delivering/done 由配送签收环节推进，不在本模块。
  pick:    created→picking→done→cancelled
           §8.2 无「开始分拣」端点，故 created→done 亦合法；cancelled 为终态。

库存事务（硬约束）：分拣扣减在**同一事务**内同时写
  batch_stock（结存，行锁 SELECT ... FOR UPDATE）与 batch_flow（流水，flow_type=pick_sub），
  恒等式 batch_stock.qty_base = Σ batch_flow.qty_change_base 逐笔成立；
  扣减不足即抛 40900，整个请求事务回滚（「扣减失败不入配送」）。

幂等（§8.1）：summary 由 uk_req_date 保证「一个配送日一张」；pick 由 uk_idem + 同店校验保证
  重复生成不产生第二张；完成类接口以「已在目标状态即视为重放」实现重试安全。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.model.inventory import BatchFlow, BatchStock
from app.model.order import OrderHead, OrderItem
from app.model.summary import Pick, PickItem, Summary, SummaryItem
from app.schema.summary import PickCreate
from app.service.order_service import build_doc_no, quantize_qty
from app.service.store_service import (
    PageResult,
    _find_one,
    _load_or_404,
    _not_deleted,
    _page_query,
    fingerprint_payload,
)

# --------------------------------------------------------------------------- 常量
SUMMARY_NO_PREFIX = "HZ"
PICK_NO_PREFIX = "FJ"
# 总部仓 store_id（§7.2：0=总部仓，其余=门店）
WAREHOUSE_STORE_ID = 0
# 汇总数据源：已确认 + 已汇总（重算汇总单时不能漏掉已并入本单的 merged 单）
ORDER_SUMMARY_SOURCES: tuple[str, ...] = ("confirmed", "merged")
# 状态机值域
SUMMARY_STATUSES: tuple[str, ...] = ("generated", "picking", "picked", "delivering", "done")
PICK_STATUSES: tuple[str, ...] = ("created", "picking", "done", "cancelled")
SUMMARY_STATUS_GENERATED = "generated"
SUMMARY_STATUS_PICKING = "picking"
SUMMARY_STATUS_PICKED = "picked"
PICK_STATUS_CREATED = "created"
PICK_STATUS_DONE = "done"
PICK_STATUS_CANCELLED = "cancelled"
# 允许生成分拣单的汇总单状态（delivering/done 已进入配送环节，不可重拣）
PICK_ALLOWED_SUMMARY_STATUSES: tuple[str, ...] = (SUMMARY_STATUS_GENERATED, SUMMARY_STATUS_PICKING)
# 允许「分拣完成」的前置状态（§8.2 无开始分拣端点，created 可直接完成）
PICK_COMPLETE_FROM: tuple[str, ...] = (PICK_STATUS_CREATED, "picking")


# --------------------------------------------------------------------------- 装配投影
def attach_summary_items(db: Session, summaries: Sequence[Summary]) -> None:
    """装配汇总明细投影字段 items（一次查询覆盖整页，避免 N+1）。"""
    ids = [int(row.id) for row in summaries]
    grouped: dict[int, list[SummaryItem]] = {}
    if ids:
        rows = db.scalars(
            select(SummaryItem)
            .where(SummaryItem.summary_id.in_(ids))
            .order_by(SummaryItem.summary_id, SummaryItem.sku_id)
        ).all()
        for row in rows:
            grouped.setdefault(int(row.summary_id), []).append(row)
    for summary in summaries:
        summary.items = grouped.get(int(summary.id), [])


def attach_pick_items(db: Session, picks: Sequence[Pick]) -> None:
    """装配分拣明细投影字段 items（批次落定结果）。"""
    ids = [int(row.id) for row in picks]
    grouped: dict[int, list[PickItem]] = {}
    if ids:
        rows = db.scalars(
            select(PickItem)
            .where(PickItem.pick_id.in_(ids))
            .order_by(PickItem.pick_id, PickItem.sku_id, PickItem.id)
        ).all()
        for row in rows:
            grouped.setdefault(int(row.pick_id), []).append(row)
    for pick in picks:
        pick.items = grouped.get(int(pick.id), [])


# --------------------------------------------------------------------------- 查询
def get_summary(db: Session, summary_id: int) -> Summary:
    """按 id 取汇总单（含 SKU 明细）；不存在 40400。"""
    summary = _load_or_404(db, Summary, summary_id, "汇总单")
    attach_summary_items(db, [summary])
    return summary


def list_summaries(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    require_date: date | None = None,
    status: str | None = None,
) -> PageResult[Summary]:
    """汇总单分页查询（§8.2 GET /summaries?require_date=&status=）。"""
    conditions: list[Any] = [_not_deleted(Summary)]
    if require_date is not None:
        conditions.append(Summary.require_date == require_date)
    if status is not None:
        if status not in SUMMARY_STATUSES:
            raise ConflictError(f"汇总单状态非法：{status}")
        conditions.append(Summary.status == status)
    result = _page_query(
        db,
        Summary,
        conditions,
        page=page,
        page_size=page_size,
        order_by=(Summary.require_date.desc(), Summary.id.desc()),
    )
    attach_summary_items(db, result.items)
    return result


def get_pick(db: Session, pick_id: int) -> Pick:
    """按 id 取分拣单（含批次明细）；不存在 40400。供配送环节复用。"""
    pick = _load_or_404(db, Pick, pick_id, "分拣单")
    attach_pick_items(db, [pick])
    return pick


def list_picks(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    summary_id: int | None = None,
    store_id: int | None = None,
    status: str | None = None,
    require_date: date | None = None,
) -> PageResult[Pick]:
    """分拣单分页查询（GET /picks，供分拣页与配送环节复用）。

    require_date 通过子查询限定所属汇总单的配送日（分拣单本身不存该列）。
    """
    conditions: list[Any] = [_not_deleted(Pick)]
    if require_date is not None:
        conditions.append(
            Pick.summary_id.in_(
                select(Summary.id).where(
                    _not_deleted(Summary), Summary.require_date == require_date
                )
            )
        )
    if summary_id is not None:
        conditions.append(Pick.summary_id == int(summary_id))
    if store_id is not None:
        conditions.append(Pick.store_id == int(store_id))
    if status is not None:
        if status not in PICK_STATUSES:
            raise ConflictError(f"分拣单状态非法：{status}")
        conditions.append(Pick.status == status)
    result = _page_query(
        db,
        Pick,
        conditions,
        page=page,
        page_size=page_size,
        order_by=(Pick.id.desc(),),
    )
    attach_pick_items(db, result.items)
    return result


# --------------------------------------------------------------------------- 汇总
def _aggregate_rows(db: Session, require_date: date) -> list[Any]:
    """按 SKU 聚合该配送日全部 confirmed/merged 要货单的 qty_base。"""
    stmt = (
        select(OrderItem.sku_id, func.sum(OrderItem.qty_base).label("total_qty_base"))
        .join(OrderHead, OrderHead.id == OrderItem.order_id)
        .where(
            _not_deleted(OrderHead),
            OrderHead.require_date == require_date,
            OrderHead.status.in_(ORDER_SUMMARY_SOURCES),
        )
        .group_by(OrderItem.sku_id)
        .order_by(OrderItem.sku_id)
    )
    return list(db.execute(stmt).all())


def _write_summary_items(
    db: Session, summary: Summary, rows: Sequence[Any], operator_id: int | None
) -> None:
    """整单重写汇总明细（明细随头失效、不单独软删）：重复触发幂等且能纳入迟到的确认单。"""
    db.execute(delete(SummaryItem).where(SummaryItem.summary_id == summary.id))
    for row in rows:
        db.add(
            SummaryItem(
                summary_id=summary.id,
                sku_id=int(row.sku_id),
                total_qty_base=quantize_qty(row.total_qty_base),
                created_by=operator_id,
                updated_by=operator_id,
            )
        )
    summary.line_count = len(rows)


def _mark_orders_merged(db: Session, require_date: date, operator_id: int | None) -> None:
    """汇总落定即把当日 confirmed 要货单推进为 merged（§7.3 状态机 confirmed→merged）。"""
    db.execute(
        update(OrderHead)
        .where(
            _not_deleted(OrderHead),
            OrderHead.require_date == require_date,
            OrderHead.status == "confirmed",
        )
        .values(status="merged", updated_by=operator_id, version=OrderHead.version + 1)
    )


def generate_summary(
    db: Session,
    *,
    require_date: date,
    operator_id: int | None = None,
    idempotency_key: str | None = None,
) -> Summary:
    """按配送日聚合全部 confirmed 要货单 → summary + summary_item（幂等 uk_req_date）。

    - 该配送日已有汇总单：状态仍为 generated（尚未分拣）时按最新 confirmed/merged 单重算明细，
      保证迟到的确认单不会漏汇总；已进入 picking 及以后则原样返回，不再改动已落定的行。
    - 该配送日无汇总单且无 confirmed 单：40400（不落空汇总单，避免占用 uk_req_date）。
    """
    existing = _find_one(db, Summary, Summary.require_date == require_date)
    if existing is not None:
        # 行锁：并发重复触发时串行重算，避免两个请求同时重写同一张汇总单明细
        locked = db.scalar(select(Summary).where(Summary.id == existing.id).with_for_update())
        if locked is not None:
            existing = locked
        if existing.status == SUMMARY_STATUS_GENERATED:
            rows = _aggregate_rows(db, require_date)
            _write_summary_items(db, existing, rows, operator_id)
            _mark_orders_merged(db, require_date, operator_id)
            if idempotency_key and not existing.idempotency_key:
                existing.idempotency_key = idempotency_key
            existing.updated_by = operator_id
            db.flush()
        attach_summary_items(db, [existing])
        return existing

    rows = _aggregate_rows(db, require_date)
    if not rows:
        raise NotFoundError("该配送日没有已确认的要货单，无法生成汇总单")

    summary = Summary(
        summary_no=build_doc_no(
            db,
            model=Summary,
            column=Summary.summary_no,
            prefix=SUMMARY_NO_PREFIX,
            on_date=require_date,
        ),
        require_date=require_date,
        status=SUMMARY_STATUS_GENERATED,
        line_count=len(rows),
        idempotency_key=idempotency_key,
        created_by=operator_id,
        updated_by=operator_id,
    )
    try:
        # savepoint：并发撞 uk_req_date 时只回滚本次写入，再回查已存在的那张
        with db.begin_nested():
            db.add(summary)
            db.flush()
            _write_summary_items(db, summary, rows, operator_id)
            _mark_orders_merged(db, require_date, operator_id)
            db.flush()
    except IntegrityError:
        existing = _find_one(db, Summary, Summary.require_date == require_date)
        if existing is None:
            raise
        summary = existing
    attach_summary_items(db, [summary])
    return summary


# --------------------------------------------------------------------------- 分拣
def _fifo_allocate(
    db: Session, pick: Pick, orders: Sequence[OrderHead], *, operate_by: int | None
) -> list[PickItem]:
    """FIFO 扣减总部仓批次库存并落分拣明细（同一事务）。

    步骤：① 取本店该配送日全部要货明细；② 按 (store_id=0, sku, qty_base>0) 取批次结存行
    并 SELECT ... FOR UPDATE 行锁，按 expire_at 升序；③ 逐行 FIFO 分配；
    ④ 写 pick_item + 扣 batch_stock + 写 batch_flow(pick_sub)，行行对账。
    """
    order_ids = [int(order.id) for order in orders]
    lines = list(
        db.scalars(
            select(OrderItem)
            .where(OrderItem.order_id.in_(order_ids))
            .order_by(OrderItem.order_id, OrderItem.id)
        ).all()
    )
    if not lines:
        raise NotFoundError("要货单没有明细，无法生成分拣单")
    sku_ids = sorted({int(line.sku_id) for line in lines})

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
            .with_for_update()
        ).all()
    )

    queue: dict[int, list[BatchStock]] = {}
    remaining: dict[tuple[int, str], Decimal] = {}
    for batch in batches:
        queue.setdefault(int(batch.sku_id), []).append(batch)
        remaining[(int(batch.sku_id), batch.batch_no)] = quantize_qty(batch.qty_base)

    allocations: dict[tuple[int, str], Decimal] = {}
    for line in lines:
        need = quantize_qty(line.qty_base)
        picked: list[str] = []
        for batch in queue.get(int(line.sku_id), []):
            if need <= 0:
                break
            key = (int(line.sku_id), batch.batch_no)
            available = remaining.get(key, Decimal("0.000"))
            if available <= 0:
                continue
            take = available if available < need else need
            remaining[key] = available - take
            allocations[key] = allocations.get(key, Decimal("0.000")) + take
            picked.append(batch.batch_no)
            need -= take
        if need > 0:
            raise ConflictError(
                f"总部仓批次库存不足：SKU {line.sku_id} 缺口 {need}（要货明细 {line.id}）"
            )
        if len(set(picked)) == 1:
            # 单批次即满足时回填要货明细 batch_no，串起「要货→实际出库批次」；
            # 多批次时以 pick_item 为准
            line.batch_no = picked[0]
        line.updated_by = operate_by

    batch_by_key = {(int(batch.sku_id), batch.batch_no): batch for batch in batches}
    occurred_at = datetime.now()
    items: list[PickItem] = []
    for key in sorted(allocations, key=lambda item: (item[0], item[1])):
        sku_id, batch_no = key
        qty = quantize_qty(allocations[key])
        if qty <= 0:
            continue
        item = PickItem(
            pick_id=pick.id,
            sku_id=sku_id,
            batch_no=batch_no,
            qty_base=qty,
            created_by=operate_by,
            updated_by=operate_by,
        )
        db.add(item)
        db.flush()
        batch = batch_by_key[key]
        qty_after = quantize_qty(batch.qty_base) - qty
        batch.qty_base = qty_after
        batch.version = int(batch.version or 0) + 1
        batch.updated_by = operate_by
        db.add(
            BatchFlow(
                store_id=batch.store_id,
                sku_id=sku_id,
                batch_no=batch_no,
                flow_type="pick_sub",
                qty_change_base=-qty,
                qty_after_base=qty_after,
                expire_at=batch.expire_at,
                doc_type="pick",
                doc_id=pick.id,
                doc_no=pick.pick_no,
                doc_item_id=item.id,
                operate_by=int(operate_by or 0),
                occurred_at=occurred_at,
                remark=f"分拣扣减→门店 {pick.store_id}",
            )
        )
        items.append(item)
    db.flush()
    return items


def create_pick(
    db: Session,
    payload: PickCreate,
    *,
    operator_id: int | None = None,
    idempotency_key: str | None = None,
) -> Pick:
    """按门店生成分拣单：FIFO 锁批次扣减总部仓库存，同事务写 batch_flow（§8.2 POST /picks）。"""
    request_fp = fingerprint_payload(
        {"summary_id": int(payload.summary_id), "store_id": int(payload.store_id)}
    )
    if idempotency_key:
        existing = _find_one(db, Pick, Pick.idempotency_key == idempotency_key)
        if existing is not None:
            existing_fp = fingerprint_payload(
                {"summary_id": int(existing.summary_id), "store_id": int(existing.store_id)}
            )
            if existing_fp != request_fp:
                raise ConflictError("幂等键重复且分拣单内容与首次提交不一致")
            attach_pick_items(db, [existing])
            return existing

    summary = _load_or_404(db, Summary, int(payload.summary_id), "汇总单")
    # 行锁：同一汇总单下的分拣单生成串行化，杜绝并发重复生成/重复扣减库存
    locked_summary = db.scalar(select(Summary).where(Summary.id == summary.id).with_for_update())
    if locked_summary is not None:
        summary = locked_summary
    if summary.status not in PICK_ALLOWED_SUMMARY_STATUSES:
        raise ConflictError(f"汇总单当前状态为 {summary.status}，不能生成分拣单")
    duplicate = _find_one(
        db,
        Pick,
        Pick.summary_id == summary.id,
        Pick.store_id == int(payload.store_id),
        Pick.status != PICK_STATUS_CANCELLED,
    )
    if duplicate is not None:
        raise ConflictError("该门店已存在分拣单，如需重拣请先取消原分拣单后重试")

    orders = list(
        db.scalars(
            select(OrderHead)
            .where(
                _not_deleted(OrderHead),
                OrderHead.require_date == summary.require_date,
                OrderHead.store_id == int(payload.store_id),
                OrderHead.status.in_(ORDER_SUMMARY_SOURCES),
            )
            .order_by(OrderHead.id)
        ).all()
    )
    if not orders:
        raise NotFoundError("该门店在该配送日没有已确认/已汇总的要货单")

    pick = Pick(
        pick_no=build_doc_no(
            db,
            model=Pick,
            column=Pick.pick_no,
            prefix=PICK_NO_PREFIX,
            on_date=summary.require_date,
        ),
        summary_id=summary.id,
        store_id=int(payload.store_id),
        status=PICK_STATUS_CREATED,
        idempotency_key=idempotency_key,
        created_by=operator_id,
        updated_by=operator_id,
    )
    db.add(pick)
    db.flush()
    _fifo_allocate(db, pick, orders, operate_by=operator_id)
    if summary.status == SUMMARY_STATUS_GENERATED:
        summary.status = SUMMARY_STATUS_PICKING
        summary.updated_by = operator_id
    db.flush()
    attach_pick_items(db, [pick])
    return pick


def complete_pick(db: Session, pick_id: int, *, operator_id: int | None = None) -> Pick:
    """分拣完成：pick.created/picking→done；该汇总单全部分拣单完成时 summary→picked。"""
    pick = _load_or_404(db, Pick, pick_id, "分拣单")
    if pick.status == PICK_STATUS_DONE:
        attach_pick_items(db, [pick])
        return pick
    if pick.status not in PICK_COMPLETE_FROM:
        raise ConflictError(f"分拣单当前状态为 {pick.status}，不能完成")
    pick.status = PICK_STATUS_DONE
    pick.version = int(pick.version or 0) + 1
    pick.updated_by = operator_id
    db.flush()

    summary = db.get(Summary, int(pick.summary_id))
    if summary is not None and summary.status in (SUMMARY_STATUS_GENERATED, SUMMARY_STATUS_PICKING):
        siblings = list(
            db.scalars(
                select(Pick).where(
                    _not_deleted(Pick),
                    Pick.summary_id == summary.id,
                    Pick.status != PICK_STATUS_CANCELLED,
                )
            ).all()
        )
        if siblings and all(sibling.status == PICK_STATUS_DONE for sibling in siblings):
            summary.status = SUMMARY_STATUS_PICKED
            summary.updated_by = operator_id
            db.flush()
    attach_pick_items(db, [pick])
    return pick
