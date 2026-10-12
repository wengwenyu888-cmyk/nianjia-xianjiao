"""对账与核算服务（§7.5 reconcile 模型 + §8.2 对账核算组端点）。

分层铁律：本层是唯一的事务边界与业务判定处；不感知 HTTP，只抛 BusinessError 子类。

职责：
- generate_reconcile：按周期（YYYY-Www / YYYY-MM / YYYY）聚合配送签收数据，逐店生成对账单；
  幂等锚点是唯一索引 uk_store_period(store_id, period, deleted_at)——重复生成返回既有行，
  不覆盖已确认数据（作废重生成需先软删旧行，本期无该端点）。
- confirm_reconcile：记录与管家婆的差异额（diff_amount），状态 draft → confirmed → done。
- store_profit：门店盈亏 = 收入 - 配货成本；配货成本与对账单 total_amount 同源同口径。
- store_kpi：损耗率 / 要货准确率 / 周转天数，全部走 SQL 聚合（func.sum/count），
  且只统计未软删数据（delivery/loss/order_head/reconcile 均带 deleted_at 哨兵过滤；
  batch_flow 仅追加无软删；SKU/Price 不滤软删——历史核算需要已停用主数据的当时价）。

口径（docs/01 业务手册 + §7 表注释）：
- 内部结算额 = Σ 签收实收量 ÷ SKU 换算系数 × 当时价（内部调拨价优先，缺失退采购价）；
  无当时价的 SKU 计入 0（不臆造价格），差异由对账环节人工确认。
- 损耗率 = 已审批报损量 ÷ 签收入库量（业务手册：「损耗量 ÷ 入库量」）。
- 要货准确率 = 1 - Σ|要货量 - 实收量| ÷ Σ要货量（按 SKU 汇总后逐 SKU 比较，
  避免明细 join 造成的行放大）；配送准确率 = 1 - Σ|应送 - 实收| ÷ Σ应送（签收差异率）。
- 周转天数 = 周期平均库存 ÷ 日均出库量；期初 = 期末结存 - 周期内 batch_flow 净变动，
  出库量 = 周期内负向流水之和（流水台账口径，日终与 batch_stock 恒等式自洽）。
- 收入（门店流水）来自银豹 POS 对接，本数据模型内没有该表：revenue 缺省 0 并由调用方显式传入。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import (
    BusinessError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.model.base import SOFT_DELETE_SENTINEL
from app.model.delivery import Delivery, Sign, SignItem
from app.model.inventory import BatchFlow, BatchStock
from app.model.loss import Loss, Reconcile
from app.model.order import OrderHead, OrderItem
from app.model.store import Price, Sku, Store
from app.schema.settlement import ReconcileConfirm
from app.service.delivery_service import Actor
from app.service.store_service import PageResult
from app.utils.unit import money

# 周期写法（与 reconcile.period 的「如 2026-W42」一致）
_WEEK_RE = re.compile(r"^(\d{4})-W(\d{1,2})$")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_YEAR_RE = re.compile(r"^(\d{4})$")
# 要货量口径：只有生效（confirmed/merged）的要货单计入准确率
_ORDER_ACTIVE_STATUSES = ("confirmed", "merged")
ZERO = Decimal("0")


# --------------------------------------------------------------------------- 周期
@dataclass(frozen=True)
class PeriodWindow:
    """对账周期窗口：start 含、end 不含。"""

    code: str
    start: date
    end: date

    @property
    def days(self) -> int:
        return max(1, (self.end - self.start).days)

    @property
    def last_day(self) -> date:
        """周期末日（含），当时价按该日取值。"""
        return self.end - timedelta(days=1)

    @property
    def start_at(self) -> datetime:
        return datetime.combine(self.start, time.min)

    @property
    def end_at(self) -> datetime:
        return datetime.combine(self.end, time.min)


def parse_period(code: str) -> PeriodWindow:
    """解析对账周期：YYYY-Www（ISO 周，周一起）/ YYYY-MM（自然月）/ YYYY（自然年）。"""
    text = (code or "").strip()
    week = _WEEK_RE.match(text)
    if week:
        year, week_no = int(week.group(1)), int(week.group(2))
        if not 1 <= week_no <= 53:
            raise BusinessError(f"对账周期不合法：{text}")
        try:
            start = datetime.strptime(f"{year}-W{week_no:02d}-1", "%G-W%V-%u").date()
        except ValueError as exc:
            raise BusinessError(f"对账周期不合法：{text}") from exc
        return PeriodWindow(
            code=f"{year}-W{week_no:02d}", start=start, end=start + timedelta(days=7)
        )
    month = _MONTH_RE.match(text)
    if month:
        year, month_no = int(month.group(1)), int(month.group(2))
        if not 1 <= month_no <= 12:
            raise BusinessError(f"对账周期不合法：{text}")
        start = date(year, month_no, 1)
        end = date(year + 1, 1, 1) if month_no == 12 else date(year, month_no + 1, 1)
        return PeriodWindow(code=f"{year}-{month_no:02d}", start=start, end=end)
    year_only = _YEAR_RE.match(text)
    if year_only:
        year = int(year_only.group(1))
        if not 2000 <= year <= 2999:
            raise BusinessError(f"对账周期不合法：{text}")
        return PeriodWindow(code=f"{year}", start=date(year, 1, 1), end=date(year + 1, 1, 1))
    raise BusinessError("对账周期格式应为 YYYY-Www / YYYY-MM / YYYY，例如 2026-W42")


# --------------------------------------------------------------------------- 结果聚合
@dataclass(frozen=True)
class ReconcileBatch:
    """生成结果：rows=本次涉及的对账单，generated=新建条数，reused=幂等复用条数。"""

    period: str
    rows: list[Reconcile]
    generated: int
    reused: int


@dataclass(frozen=True)
class StoreProfit:
    """门店盈亏聚合结果。"""

    store: Store
    window: PeriodWindow
    revenue: Decimal
    revenue_source: str
    delivery_cost: Decimal
    gross_profit: Decimal
    gross_margin: Decimal | None
    loss_qty: Decimal
    sign_qty: Decimal
    reconcile: Reconcile | None


@dataclass(frozen=True)
class StoreKpi:
    """门店 KPI 聚合结果。"""

    store: Store
    window: PeriodWindow
    gross_in_qty: Decimal
    loss_qty: Decimal
    loss_rate: Decimal | None
    order_qty: Decimal
    order_accuracy: Decimal | None
    send_qty: Decimal
    delivery_accuracy: Decimal | None
    stock_qty: Decimal
    opening_stock_qty: Decimal
    avg_stock_qty: Decimal
    outbound_qty: Decimal
    turnover_days: Decimal | None


# --------------------------------------------------------------------------- 内部工具
def _not_deleted(model: Any) -> Any:
    return model.deleted_at == SOFT_DELETE_SENTINEL


def _dec(value: Any) -> Decimal:
    """SQL 聚合值归一化：NULL 与 int 0 都按 Decimal(0) 处理。"""
    return Decimal(str(value if value is not None else 0))


def _ratio(numerator: Any, denominator: Any, *, places: str = "0.0001") -> Decimal | None:
    """比值：分母为 0 → None（不返回 0 冒充「无数据」）。"""
    bottom = _dec(denominator)
    if bottom == 0:
        return None
    return (_dec(numerator) / bottom).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _accuracy(variance: Any, total: Any) -> Decimal | None:
    """准确率 = 1 - 差异量/总量，落在 [0,1]；无分母 → None。"""
    ratio = _ratio(variance, total)
    if ratio is None:
        return None
    value = (Decimal(1) - ratio).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return max(ZERO, min(Decimal(1), value))


def _page_query(
    db: Session,
    model: Any,
    conditions: Sequence[Any],
    *,
    page: int,
    page_size: int,
    order_by: Sequence[Any],
) -> PageResult[Any]:
    """分页查询：先 count 再取页（与 store_service 同口径）。"""
    total = int(db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0)
    stmt = (
        select(model)
        .where(*conditions)
        .order_by(*order_by)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return PageResult(items=list(db.scalars(stmt).all()), total=total)


def _require_store(db: Session, store_id: int) -> Store:
    store = db.scalar(select(Store).where(_not_deleted(Store), Store.id == store_id))
    if store is None:
        raise NotFoundError("门店不存在")
    return store


def _assert_store_scope(actor: Actor | None, store_id: int) -> None:
    """数据范围：门店账号（store_id 非空）只能看/生成本店核算数据。"""
    if actor is not None and actor.store_id is not None and actor.store_id != store_id:
        raise PermissionDeniedError("只能查看本店的核算数据")


def resolve_store_scope(actor: Actor | None, store_id: int | None) -> int | None:
    """列表数据范围：门店账号强制本店（显式请求他店 → 40300），总部账号按入参。"""
    if actor is None or actor.store_id is None:
        return store_id
    if store_id is not None and store_id != actor.store_id:
        raise PermissionDeniedError("只能查看本店的核算数据")
    return actor.store_id


# --------------------------------------------------------------------------- 聚合查询
def _sign_rows(
    db: Session, window: PeriodWindow, store_ids: Sequence[int] | None = None
) -> list[tuple[int, int, Decimal]]:
    """按 (门店, SKU) 聚合签收实收量；只统计未软删的配送单（签收单无软删）。"""
    conditions: list[Any] = [
        _not_deleted(Delivery),
        Delivery.require_date >= window.start,
        Delivery.require_date < window.end,
    ]
    if store_ids:
        conditions.append(Delivery.store_id.in_(list(store_ids)))
    stmt = (
        select(Delivery.store_id, SignItem.sku_id, func.sum(SignItem.sign_qty_base))
        .select_from(SignItem)
        .join(Sign, Sign.id == SignItem.sign_id)
        .join(Delivery, Delivery.id == Sign.delivery_id)
        .where(*conditions)
        .group_by(Delivery.store_id, SignItem.sku_id)
    )
    return [(int(row[0]), int(row[1]), _dec(row[2])) for row in db.execute(stmt).all()]


def _sign_totals(
    db: Session, store_id: int, window: PeriodWindow
) -> tuple[Decimal, Decimal, Decimal]:
    """门店周期内签收汇总：(应送量, 实收量, |差异| 合计)。"""
    stmt = (
        select(
            func.coalesce(func.sum(SignItem.send_qty_base), 0),
            func.coalesce(func.sum(SignItem.sign_qty_base), 0),
            func.coalesce(func.sum(func.abs(SignItem.diff_qty_base)), 0),
        )
        .select_from(SignItem)
        .join(Sign, Sign.id == SignItem.sign_id)
        .join(Delivery, Delivery.id == Sign.delivery_id)
        .where(
            _not_deleted(Delivery),
            Delivery.store_id == store_id,
            Delivery.require_date >= window.start,
            Delivery.require_date < window.end,
        )
    )
    row = db.execute(stmt).one()
    return _dec(row[0]), _dec(row[1]), _dec(row[2])


def _sign_qty_by_sku(db: Session, store_id: int, window: PeriodWindow) -> dict[int, Decimal]:
    """按 SKU 汇总签收实收量（_sign_rows 已按门店过滤）。"""
    return {sku_id: qty for _, sku_id, qty in _sign_rows(db, window, [store_id])}


def _order_qty_by_sku(db: Session, store_id: int, window: PeriodWindow) -> dict[int, Decimal]:
    """按 SKU 汇总生效要货量（confirmed/merged，未取消、未软删）。"""
    stmt = (
        select(OrderItem.sku_id, func.sum(OrderItem.qty_base))
        .select_from(OrderItem)
        .join(OrderHead, OrderHead.id == OrderItem.order_id)
        .where(
            _not_deleted(OrderHead),
            OrderHead.store_id == store_id,
            OrderHead.require_date >= window.start,
            OrderHead.require_date < window.end,
            OrderHead.status.in_(_ORDER_ACTIVE_STATUSES),
        )
        .group_by(OrderItem.sku_id)
    )
    return {int(row[0]): _dec(row[1]) for row in db.execute(stmt).all()}


def _loss_qty(db: Session, store_id: int, window: PeriodWindow) -> Decimal:
    """周期内已审批报损量（按 loss.created_at 归期，与 idx_store_created 的查询路径一致）。"""
    value = db.scalar(
        select(func.coalesce(func.sum(Loss.qty_base), 0)).where(
            _not_deleted(Loss),
            Loss.store_id == store_id,
            Loss.status == "approved",
            Loss.created_at >= window.start_at,
            Loss.created_at < window.end_at,
        )
    )
    return _dec(value)


def _price_map(db: Session, sku_ids: Sequence[int], on_date: date) -> dict[int, Decimal]:
    """当时价：命中生效区间 [effective_from, effective_to]，同 SKU 取生效日最近的一条；
    内部调拨价优先，缺失退采购价。无价目的 SKU 不在结果里（对账按 0 计）。"""
    skus = sorted({int(sku_id) for sku_id in sku_ids})
    if not skus:
        return {}
    rows = db.execute(
        select(Price.sku_id, Price.price_type, Price.price)
        .where(
            _not_deleted(Price),
            Price.sku_id.in_(skus),
            Price.effective_from <= on_date,
            or_(Price.effective_to.is_(None), Price.effective_to >= on_date),
        )
        .order_by(Price.sku_id.asc(), Price.effective_from.desc())
    ).all()
    latest: dict[int, dict[str, Decimal]] = {}
    for sku_id, price_type, price in rows:
        latest.setdefault(int(sku_id), {}).setdefault(str(price_type), _dec(price))
    chosen: dict[int, Decimal] = {}
    for sku_id, slot in latest.items():
        value = slot.get("transfer")
        if value is None:
            value = slot.get("purchase")
        if value is not None:
            chosen[sku_id] = value
    return chosen


def _factor_map(db: Session, sku_ids: Sequence[int]) -> dict[int, Decimal]:
    """换算系数（1 订货单位 = 多少基础单位）；不滤软删：历史核算需要已停用 SKU 的换算关系。"""
    skus = sorted({int(sku_id) for sku_id in sku_ids})
    if not skus:
        return {}
    rows = db.execute(select(Sku.id, Sku.convert_factor).where(Sku.id.in_(skus))).all()
    factors: dict[int, Decimal] = {}
    for sku_id, factor in rows:
        value = _dec(factor)
        factors[int(sku_id)] = value if value > 0 else Decimal(1)
    return factors


def _settlement_amounts(
    db: Session, window: PeriodWindow, store_ids: Sequence[int] | None = None
) -> dict[int, Decimal]:
    """按门店计算周期内部结算额：Σ 实收量 ÷ 换算系数 × 当时价（保留 2 位）。"""
    rows = _sign_rows(db, window, store_ids)
    if not rows:
        return {}
    sku_ids = {sku_id for _, sku_id, _ in rows}
    prices = _price_map(db, sku_ids, window.last_day)
    factors = _factor_map(db, sku_ids)
    amounts: dict[int, Decimal] = {}
    for store_id, sku_id, qty in rows:
        price = prices.get(sku_id)
        if price is None:
            continue
        factor = factors.get(sku_id, Decimal(1))
        amounts[store_id] = amounts.get(store_id, ZERO) + money(qty / factor * price)
    return {store_id: money(value) for store_id, value in amounts.items()}


def _store_stock_qty(db: Session, store_id: int) -> Decimal:
    """门店期末结存（未软删结存行合计）。"""
    value = db.scalar(
        select(func.coalesce(func.sum(BatchStock.qty_base), 0)).where(
            _not_deleted(BatchStock), BatchStock.store_id == store_id
        )
    )
    return _dec(value)


def _flow_stats(db: Session, store_id: int, window: PeriodWindow) -> tuple[Decimal, Decimal]:
    """周期内流水口径：(净变动, 出库量)；batch_flow 仅追加、无软删。"""
    net = db.scalar(
        select(func.coalesce(func.sum(BatchFlow.qty_change_base), 0)).where(
            BatchFlow.store_id == store_id,
            BatchFlow.occurred_at >= window.start_at,
            BatchFlow.occurred_at < window.end_at,
        )
    )
    outbound = db.scalar(
        select(func.coalesce(func.sum(-BatchFlow.qty_change_base), 0)).where(
            BatchFlow.store_id == store_id,
            BatchFlow.occurred_at >= window.start_at,
            BatchFlow.occurred_at < window.end_at,
            BatchFlow.qty_change_base < 0,
        )
    )
    return _dec(net), _dec(outbound)


# --------------------------------------------------------------------------- 对账单
def get_reconcile(db: Session, reconcile_id: int) -> Reconcile:
    """按 id 查对账单；不存在或已软删 → 40400。"""
    row = db.scalar(select(Reconcile).where(_not_deleted(Reconcile), Reconcile.id == reconcile_id))
    if row is None:
        raise NotFoundError("对账单不存在")
    return row


def list_reconciles(
    db: Session,
    *,
    period: str | None = None,
    store_id: int | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult[Reconcile]:
    """GET /reconciles?period=&store_id=：对账分页查询（仅未软删数据）。"""
    conditions: list[Any] = [_not_deleted(Reconcile)]
    if period:
        conditions.append(Reconcile.period == period)
    if store_id is not None:
        conditions.append(Reconcile.store_id == store_id)
    if status is not None:
        conditions.append(Reconcile.status == status)
    return _page_query(
        db,
        Reconcile,
        conditions,
        page=page,
        page_size=page_size,
        order_by=(Reconcile.period.desc(), Reconcile.store_id.asc(), Reconcile.id.desc()),
    )


def generate_reconcile(
    db: Session,
    *,
    period: str,
    store_ids: Sequence[int] | None = None,
    actor: Actor | None = None,
    operator_id: int | None = None,
    idempotency_key: str | None = None,
) -> ReconcileBatch:
    """POST /reconciles/generate（按周期生成对账单，幂等）。

    - 幂等锚点：uk_store_period(store_id, period, deleted_at)；命中既有行直接复用，不覆盖；
    - store_ids 缺省=该周期有签收数据的门店；显式指定时逐店建行（无数据按 0.00 建）；
    - Idempotency-Key：uk_idem(idempotency_key, deleted_at) 是「一行一键」，
      多店批量无法逐行落同键，故仅单店生成时把键落到该行；多店场景靠 uk_store_period 幂等。
    """
    window = parse_period(period)
    targets: list[int] | None = None
    if store_ids:
        targets = []
        for store_id in dict.fromkeys(int(item) for item in store_ids):
            _require_store(db, store_id)
            _assert_store_scope(actor, store_id)
            targets.append(store_id)

    amounts = _settlement_amounts(db, window, targets)
    pending = targets if targets is not None else sorted(amounts)

    if idempotency_key:
        keyed = list(
            db.scalars(
                select(Reconcile).where(
                    _not_deleted(Reconcile), Reconcile.idempotency_key == idempotency_key
                )
            ).all()
        )
        if keyed:
            if {row.period for row in keyed} != {window.code}:
                raise ConflictError("幂等键重复且请求周期与首次生成不一致")
            if {row.store_id for row in keyed} != set(pending):
                raise ConflictError("幂等键重复且请求门店与首次生成不一致")
            return ReconcileBatch(period=window.code, rows=keyed, generated=0, reused=len(keyed))

    rows: list[Reconcile] = []
    generated = 0
    reused = 0
    for store_id in pending:
        existing = db.scalar(
            select(Reconcile).where(
                _not_deleted(Reconcile),
                Reconcile.store_id == store_id,
                Reconcile.period == window.code,
            )
        )
        if existing is not None:
            reused += 1
            rows.append(existing)
            continue
        row = Reconcile(
            period=window.code,
            store_id=store_id,
            total_amount=amounts.get(store_id, money(ZERO)),
            diff_amount=money(ZERO),
            status="draft",
            created_by=operator_id,
            updated_by=operator_id,
        )
        db.add(row)
        rows.append(row)
        generated += 1
    db.flush()

    if idempotency_key and len(rows) == 1:
        used = db.scalar(
            select(Reconcile.id).where(
                _not_deleted(Reconcile), Reconcile.idempotency_key == idempotency_key
            )
        )
        if used is None:
            rows[0].idempotency_key = idempotency_key
            db.flush()
    return ReconcileBatch(period=window.code, rows=rows, generated=generated, reused=reused)


def confirm_reconcile(
    db: Session,
    reconcile_id: int,
    payload: ReconcileConfirm,
    *,
    operator_id: int | None = None,
    idempotency_key: str | None = None,
    now: datetime | None = None,
) -> Reconcile:
    """POST /reconciles/{id}/confirm：记录与管家婆差异额并推进状态。

    状态机：draft → confirmed → done（不可回退）；同状态重复确认且差异额一致按幂等返回，
    差异额不一致 40900（对应 §8.1「同键异体」语义）。
    """
    moment = now or datetime.now()
    if operator_id is None:
        raise BusinessError("确认对账单需要操作人身份")
    row = get_reconcile(db, reconcile_id)
    target = payload.status or "confirmed"
    diff = money(payload.diff_amount)

    if target == "confirmed" and row.status == "done":
        raise ConflictError("对账单已完成，不能回退为已确认")
    if row.status == target:
        if money(row.diff_amount) != diff:
            raise ConflictError("对账单已确认且本次差异额与首次确认不一致")
        return row

    if idempotency_key:
        used = db.scalar(
            select(Reconcile).where(
                _not_deleted(Reconcile), Reconcile.idempotency_key == idempotency_key
            )
        )
        if used is not None and used.id != row.id:
            raise ConflictError("幂等键已被其他对账单使用")
        if row.idempotency_key in (None, idempotency_key):
            row.idempotency_key = idempotency_key
        # 该列语义是「生成请求幂等键」（§7.5），生成时已占键则保留原键不覆盖；
        # 确认接口自身的重放保护由 (status, diff_amount) 判定，见上方同状态分支。

    if row.status == "draft":
        row.confirmed_by = operator_id
        row.confirmed_at = moment
    row.status = target
    row.diff_amount = diff
    row.updated_by = operator_id
    db.flush()
    return row


# --------------------------------------------------------------------------- 盈亏 / KPI
def store_profit(
    db: Session,
    store_id: int,
    period: str,
    *,
    revenue: Any = None,
    actor: Actor | None = None,
) -> StoreProfit:
    """GET /stores/{id}/profit?period=：门店盈亏 = 收入 - 配货成本（与对账单同口径）。

    revenue 缺省视为无外部数据源（银豹 POS 未接通），按 0 计并在 revenue_source 标注；
    传入时以传入值（元）为准，四舍五入到分。
    """
    store = _require_store(db, store_id)
    _assert_store_scope(actor, store.id)
    window = parse_period(period)

    cost = _settlement_amounts(db, window, [store.id]).get(store.id, money(ZERO))
    _, sign_qty, _ = _sign_totals(db, store.id, window)
    loss_qty = _loss_qty(db, store.id, window)
    revenue_value = money(revenue) if revenue is not None else money(ZERO)
    profit = money(revenue_value - cost)
    margin = _ratio(profit, revenue_value) if revenue_value != 0 else None
    reconcile = db.scalar(
        select(Reconcile).where(
            _not_deleted(Reconcile),
            Reconcile.store_id == store.id,
            Reconcile.period == window.code,
        )
    )
    return StoreProfit(
        store=store,
        window=window,
        revenue=revenue_value,
        revenue_source="external" if revenue is not None else "unavailable",
        delivery_cost=cost,
        gross_profit=profit,
        gross_margin=margin,
        loss_qty=loss_qty,
        sign_qty=sign_qty,
        reconcile=reconcile,
    )


def store_kpi(
    db: Session,
    store_id: int,
    period: str,
    *,
    actor: Actor | None = None,
) -> StoreKpi:
    """GET /stores/{id}/kpi?period=：损耗率 / 要货准确率 / 配送准确率 / 周转天数。"""
    store = _require_store(db, store_id)
    _assert_store_scope(actor, store.id)
    window = parse_period(period)

    send_qty, sign_qty, abs_diff = _sign_totals(db, store.id, window)
    loss_qty = _loss_qty(db, store.id, window)

    order_by_sku = _order_qty_by_sku(db, store.id, window)
    sign_by_sku = _sign_qty_by_sku(db, store.id, window)
    order_total = sum(order_by_sku.values(), ZERO)
    variance = sum(
        (
            abs(order_by_sku.get(sku_id, ZERO) - sign_by_sku.get(sku_id, ZERO))
            for sku_id in set(order_by_sku) | set(sign_by_sku)
        ),
        ZERO,
    )

    stock_qty = _store_stock_qty(db, store.id)
    net_change, outbound = _flow_stats(db, store.id, window)
    opening_stock = stock_qty - net_change
    avg_stock = (opening_stock + stock_qty) / 2
    daily_outbound = outbound / Decimal(window.days)
    turnover_days = (
        (avg_stock / daily_outbound).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if daily_outbound > 0
        else None
    )

    return StoreKpi(
        store=store,
        window=window,
        gross_in_qty=sign_qty,
        loss_qty=loss_qty,
        loss_rate=_ratio(loss_qty, sign_qty),
        order_qty=order_total,
        order_accuracy=_accuracy(variance, order_total),
        send_qty=send_qty,
        delivery_accuracy=_accuracy(abs_diff, send_qty),
        stock_qty=stock_qty,
        opening_stock_qty=opening_stock,
        avg_stock_qty=avg_stock,
        outbound_qty=outbound,
        turnover_days=turnover_days,
    )
