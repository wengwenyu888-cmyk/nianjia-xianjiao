"""库存查询服务（§8.2「库存」组三条只读端点；§7.2 batch_stock 结存 + batch_flow 流水）。

只读铁律（硬约束）：
- 三个接口全部只读：不 INSERT / UPDATE / DELETE batch_stock 与 batch_flow；
- 一律不使用 SELECT ... FOR UPDATE（只读查询不能挡住分拣/签收的事务扣减）；
- 库存写路径只在收货（purchase）、分拣扣减（summary）、签收入库（delivery）、
  报损审批（loss）各模块，且必须同事务写「结存 + 流水」。

软删口径：
- batch_stock 有 deleted_at 哨兵（§7 通用约定），所有查询一律 _not_deleted 过滤；
- batch_flow 仅追加、无 deleted_at（§7.2 设计理由③），天然全量历史，不加软删条件。

时间口径：全程 naive 本地时间（DDL DATETIME + datetime.now()），与 summary_service /
delivery_service 一致；aware / naive 混用会让 MySQL DATETIME 比较静默丢行。

量纲：qty_base / qty_change_base / qty_after_base 一律基础单位（DECIMAL(14,3)），
展示单位换算由前端用 unit / convert_factor 完成（本层不改数量口径）。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.model.inventory import BatchFlow, BatchStock
from app.model.store import Sku, Store
from app.schema.stock import (
    StockAlertItem,
    StockAlertsOut,
    StockAlertSummary,
    StockFlowOut,
    StockOut,
)
from app.service.order_service import quantize_qty
from app.service.store_service import PageResult, _not_deleted

# --------------------------------------------------------------------------- 常量与阈值
# 总部仓在 batch_stock.store_id / batch_flow.store_id 中的约定值（§7.2：0=总部仓，其余=门店）。
WAREHOUSE_STORE_ID = 0
# 总部仓展示名：store 表不会有 id=0 的行，投影 store_name 时用该常量兜底。
WAREHOUSE_NAME = "总部仓"

# ---- 临期阈值（小时）：日后调参只改这里 ------------------------------------------------
# ① GET /stocks 未传 expire_within_hours 时，expiring 标记的判定阈值（不影响返回行数）；
DEFAULT_EXPIRE_WITHIN_HOURS = 24
# ② GET /stocks/alerts 未传 expire_hours 时，临期清单的扫描窗口（与 ① 同值，口径一致）。
DEFAULT_ALERT_EXPIRE_HOURS = 24

# ---- 低库存阈值（基础单位）：日后调参只改这里 ------------------------------------------
# GET /stocks/alerts 未传 low_qty_base 时使用；口径 = 范围内按 SKU 聚合结存 < 阈值即预警。
DEFAULT_LOW_QTY_BASE = Decimal("20.000")

# ---- 预警清单条数：alerts 无分页（§8.2），以 limit 约束，不突破 page_size 上限 ---------
DEFAULT_ALERT_LIMIT = 50
MAX_ALERT_LIMIT = 200  # 与 §8.1 page_size 上限（200）对齐

# 数量三位小数（对齐 DECIMAL(14,3)）；小时数两位小数，便于展示（已过期为负值）。
QTY_EXP = Decimal("0.001")
HOURS_EXP = Decimal("0.01")

# flow_type 值域（§7.2 batch_flow.flow_type）；非法值 → 40000（参数校验失败）。
STOCK_FLOW_TYPES: tuple[str, ...] = ("receive_add", "pick_sub", "loss_sub", "count_adjust")


# --------------------------------------------------------------------------- 投影工具
def _hours_to_expire(expire_at: datetime, now: datetime) -> Decimal:
    """距到期小时数（2 位小数，已过期为负）；naive 时间相减，不引入时区。"""
    seconds = Decimal((expire_at - now).total_seconds())
    return (seconds / Decimal(3600)).quantize(HOURS_EXP, rounding=ROUND_HALF_UP)


def _store_names(db: Session, store_ids: Sequence[int]) -> dict[int, str]:
    """批量取门店名（一次查询覆盖整页，避免 N+1）。

    口径：**不过滤 Store.deleted_at**——结存/流水行仍在，门店软删后名称缺失会让库存页
    出现无名行（历史可读性优先，与 delivery_service 取历史 SKU 的做法一致）。
    """
    names = {WAREHOUSE_STORE_ID: WAREHOUSE_NAME}
    ids = sorted({int(sid) for sid in store_ids if int(sid) != WAREHOUSE_STORE_ID})
    if ids:
        rows = db.execute(select(Store.id, Store.name).where(Store.id.in_(ids))).all()
        names.update({int(row.id): row.name for row in rows})
    return names


def _build_stock_out(
    rows: Sequence[Any], *, store_names: dict[int, str], now: datetime, expire_hours: float
) -> list[StockOut]:
    """装配批次库存响应行：把 join 出来的 (BatchStock, Sku) 投影成 StockOut。

    expiring 直接用 datetime 比较（而非比较已四舍五入的 hours_to_expire），避免边界误差。
    """
    deadline = now + timedelta(hours=float(expire_hours))
    return [
        StockOut(
            id=int(stock.id),
            store_id=int(stock.store_id),
            store_name=store_names.get(int(stock.store_id)),
            sku_id=int(stock.sku_id),
            sku_no=sku.sku_no,
            sku_name=sku.name,
            batch_no=stock.batch_no,
            qty_base=quantize_qty(stock.qty_base),
            unit=sku.unit,
            convert_factor=Decimal(sku.convert_factor or 1),
            expire_at=stock.expire_at,
            hours_to_expire=_hours_to_expire(stock.expire_at, now),
            expiring=stock.expire_at <= deadline,
            created_at=stock.created_at,
        )
        for stock, sku in rows
    ]


# --------------------------------------------------------------------------- 批次库存
def list_stocks(
    db: Session,
    *,
    store_id: int | None = None,
    sku_id: int | None = None,
    batch_no: str | None = None,
    expire_within_hours: int | None = None,
    include_zero: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> PageResult[StockOut]:
    """批次库存分页（§8.2 GET /stocks）。

    - 默认只返回 qty_base > 0 的结存行；include_zero=True 时连零/负结存行一并返回
      （盘点差异排查用，正常巡检口径仍是「有货才算一行」）；
    - expire_within_hours 给定时只返回 expire_at <= now + N 小时的批次（含已过期：
      临期筛选不应漏掉已过期行），并把 N 作为 expiring 阈值；未给定时 expiring 用
      DEFAULT_EXPIRE_WITHIN_HOURS（24 小时）判定，返回行数不变；
    - 排序 expire_at 升序（FIFO 视角，命中 idx_expire）。
    """
    now = datetime.now()
    conditions: list[Any] = [_not_deleted(BatchStock)]
    if store_id is not None:
        conditions.append(BatchStock.store_id == int(store_id))
    if sku_id is not None:
        conditions.append(BatchStock.sku_id == int(sku_id))
    if batch_no:
        conditions.append(BatchStock.batch_no == batch_no)
    if expire_within_hours is not None:
        conditions.append(BatchStock.expire_at <= now + timedelta(hours=float(expire_within_hours)))
    if not include_zero:
        conditions.append(BatchStock.qty_base > 0)

    threshold = DEFAULT_EXPIRE_WITHIN_HOURS if expire_within_hours is None else expire_within_hours
    # 计数与取行共用同一 join（Sku.id 是主键，不会放大行数），保证 total 与 list 同口径。
    total = int(
        db.scalar(
            select(func.count())
            .select_from(BatchStock)
            .join(Sku, Sku.id == BatchStock.sku_id)
            .where(*conditions)
        )
        or 0
    )
    rows = db.execute(
        select(BatchStock, Sku)
        .join(Sku, Sku.id == BatchStock.sku_id)
        .where(*conditions)
        .order_by(BatchStock.expire_at.asc(), BatchStock.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return PageResult(
        items=_build_stock_out(
            rows,
            store_names=_store_names(db, [row[0].store_id for row in rows]),
            now=now,
            expire_hours=threshold,
        ),
        total=total,
    )


# --------------------------------------------------------------------------- 预警
def stock_alerts(
    db: Session,
    *,
    store_id: int | None = None,
    expire_hours: int = DEFAULT_ALERT_EXPIRE_HOURS,
    low_qty_base: Decimal = DEFAULT_LOW_QTY_BASE,
    limit: int = DEFAULT_ALERT_LIMIT,
) -> StockAlertsOut:
    """临期 + 低库存预警汇总（§8.2 GET /stocks/alerts），只读、无行锁。

    数据范围：store_id 缺省 = 总部仓（0，与低库存口径一致）；给定时只看该门店。
    两条清单共用同一范围（一个参数一个视角，避免「临期看全网、低库存看总部」的口径错位）。

    - expiring：范围内 qty_base > 0 且 expire_at <= now + expire_hours 的批次，
      按 expire_at 升序（含已过期批次：hours_to_expire 为负、expiring=True）；
    - low_stock：范围内按 SKU 聚合结存合计 < low_qty_base 的 SKU，按结存升序。
      聚合**不过滤 qty_base > 0**：被领用至 0 的批次行仍要算进来，否则「已耗尽的 SKU」
      会因没有任何正结存行而整行消失、漏报最该报的缺货；batch_count 只数仍有结存的批次数；
    - limit 同时约束两条清单的返回条数（超过 MAX_ALERT_LIMIT 收敛到上限）；
      summary 的计数是**命中总数（未截断）**，便于前端显示「已展示 N / 共 M」。
    """
    now = datetime.now()
    scope_store_id = WAREHOUSE_STORE_ID if store_id is None else int(store_id)
    threshold = quantize_qty(low_qty_base)
    if threshold < 0:
        raise BusinessError("低库存阈值不能用负数")
    top = max(1, min(int(limit), MAX_ALERT_LIMIT))
    deadline = now + timedelta(hours=float(expire_hours))

    expiring_conditions: list[Any] = [
        _not_deleted(BatchStock),
        BatchStock.store_id == scope_store_id,
        BatchStock.qty_base > 0,
        BatchStock.expire_at <= deadline,
    ]
    expiring_count = int(
        db.scalar(
            select(func.count())
            .select_from(BatchStock)
            .join(Sku, Sku.id == BatchStock.sku_id)
            .where(*expiring_conditions)
        )
        or 0
    )
    expiring_rows = db.execute(
        select(BatchStock, Sku)
        .join(Sku, Sku.id == BatchStock.sku_id)
        .where(*expiring_conditions)
        .order_by(BatchStock.expire_at.asc(), BatchStock.id.asc())
        .limit(top)
    ).all()

    low_stmt = (
        select(
            BatchStock.sku_id.label("sku_id"),
            Sku.sku_no.label("sku_no"),
            Sku.name.label("sku_name"),
            Sku.unit.label("unit"),
            func.sum(BatchStock.qty_base).label("qty_base"),
            func.sum(case((BatchStock.qty_base > 0, 1), else_=0)).label("batch_count"),
        )
        .join(Sku, Sku.id == BatchStock.sku_id)
        .where(_not_deleted(BatchStock), BatchStock.store_id == scope_store_id)
        .group_by(BatchStock.sku_id, Sku.id, Sku.sku_no, Sku.name, Sku.unit)
        .having(func.sum(BatchStock.qty_base) < threshold)
    )
    low_stock_count = int(db.scalar(select(func.count()).select_from(low_stmt.subquery())) or 0)
    low_rows = db.execute(
        low_stmt.order_by(func.sum(BatchStock.qty_base).asc(), BatchStock.sku_id.asc()).limit(top)
    ).all()

    return StockAlertsOut(
        expiring=_build_stock_out(
            expiring_rows,
            store_names=_store_names(db, [scope_store_id]),
            now=now,
            expire_hours=expire_hours,
        ),
        low_stock=[
            StockAlertItem(
                sku_id=int(row.sku_id),
                sku_no=row.sku_no,
                sku_name=row.sku_name,
                qty_base=quantize_qty(row.qty_base),
                unit=row.unit,
                threshold=threshold,
                batch_count=int(row.batch_count or 0),
            )
            for row in low_rows
        ],
        summary=StockAlertSummary(
            expiring_count=expiring_count,
            low_stock_count=low_stock_count,
            expire_hours=int(expire_hours),
            low_qty_base=threshold,
            as_of=now,
        ),
    )


# --------------------------------------------------------------------------- 批次流水
def list_stock_flows(
    db: Session,
    *,
    store_id: int | None = None,
    sku_id: int | None = None,
    batch_no: str | None = None,
    flow_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult[StockFlowOut]:
    """批次流水分页（§8.2 GET /stock-flows），按 occurred_at desc, id desc。

    batch_flow 仅追加、无 deleted_at（§7.2）：不加软删条件，历史流水全量可追溯；
    同秒写入的流水用 id 兜底排序，保证翻页稳定不重不漏。
    """
    if flow_type is not None and flow_type not in STOCK_FLOW_TYPES:
        raise BusinessError(f"流水类型非法：{flow_type}（可选 {'/'.join(STOCK_FLOW_TYPES)}）")

    conditions: list[Any] = []
    if store_id is not None:
        conditions.append(BatchFlow.store_id == int(store_id))
    if sku_id is not None:
        conditions.append(BatchFlow.sku_id == int(sku_id))
    if batch_no:
        conditions.append(BatchFlow.batch_no == batch_no)
    if flow_type is not None:
        conditions.append(BatchFlow.flow_type == flow_type)

    total = int(
        db.scalar(
            select(func.count())
            .select_from(BatchFlow)
            .join(Sku, Sku.id == BatchFlow.sku_id)
            .where(*conditions)
        )
        or 0
    )
    rows = db.execute(
        select(BatchFlow, Sku)
        .join(Sku, Sku.id == BatchFlow.sku_id)
        .where(*conditions)
        .order_by(BatchFlow.occurred_at.desc(), BatchFlow.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    store_names = _store_names(db, [row[0].store_id for row in rows])
    return PageResult(
        items=[
            StockFlowOut(
                id=int(flow.id),
                store_id=int(flow.store_id),
                store_name=store_names.get(int(flow.store_id)),
                sku_id=int(flow.sku_id),
                sku_no=sku.sku_no,
                sku_name=sku.name,
                batch_no=flow.batch_no,
                flow_type=flow.flow_type,
                qty_change_base=quantize_qty(flow.qty_change_base),
                qty_after_base=quantize_qty(flow.qty_after_base),
                doc_type=flow.doc_type,
                doc_no=flow.doc_no,
                operate_by=int(flow.operate_by),
                occurred_at=flow.occurred_at,
                remark=flow.remark,
            )
            for flow, sku in rows
        ],
        total=total,
    )
