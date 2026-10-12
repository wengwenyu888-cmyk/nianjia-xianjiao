"""采购服务（§7.2 purchase_order / purchase_order_item 模型 + §8.2「采购」组端点）。

分层铁律：事务边界、状态机、幂等判定只在本层；api 只做协议（不碰 model），
本层不感知 HTTP（只抛 BusinessError 子类：40000 参数 / 40400 不存在 / 40900 状态冲突）。

单据号：CG + 业务日期 + 4 位序号（复用 order_service.build_doc_no，与要货/汇总/分拣同一规则）。

幂等（§8.1）：
- 建单：请求头 Idempotency-Key → purchase_order.idempotency_key（uk_idem 唯一索引兜底），
  同键同体返回首次结果、同键异体 40900；未带键时按普通建单处理。
- 收货：以状态机 + uk_flow_source(doc_type, doc_no, flow_type, store_id, sku_id, batch_no)
  防重复入账；已收货再收货 → 40900（另支持同键重放，见 receive_purchase_order）。

库存事务（硬约束）：收货在**同一事务**内为每个 SKU 同时写
  - batch_stock（结存，store_id=0 总部仓）：新增批次行或累加既有行，取行锁 SELECT ... FOR UPDATE；
  - batch_flow（流水）：flow_type='receive_add'、doc_type='purchase_order'、doc_no=采购单号、
    qty_change_base=+本次收货量、qty_after_base=变动后结存；
  恒等式 batch_stock.qty_base = Σ batch_flow.qty_change_base 逐笔成立；
  本层不自行 commit，事务边界交由请求级 get_db（正常提交 / 异常整体回滚）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError, ConflictError, NotFoundError
from app.model.inventory import BatchFlow, BatchStock
from app.model.purchase import PurchaseOrder, PurchaseOrderItem
from app.model.store import Price, Sku, Supplier
from app.schema.purchase import AMOUNT_EXP, PurchaseCreate, ReceiveIn
from app.service.order_service import build_doc_no, quantize_qty
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
PO_NO_PREFIX = "CG"
# 总部仓 store_id（§7.2：0=总部仓，其余=门店ID）；采购收货统一入总部仓
WAREHOUSE_STORE_ID = 0
# 单价口径 DECIMAL(12,4)（purchase_order_item.price）
PRICE_EXP = Decimal("0.0001")
# 状态机（§7.2 purchase_order.status）：draft/submitted→received 由收货推进
PO_STATUSES: tuple[str, ...] = ("draft", "submitted", "received", "cancelled")
PO_RECEIVABLE_STATUSES: tuple[str, ...] = ("draft", "submitted")
PO_STATUS_DRAFT = "draft"
PO_STATUS_RECEIVED = "received"
# 批次号 = 前缀 + 两位序号；batch_stock.batch_no 为 VARCHAR(32)
BATCH_SEQ_WIDTH = 2
BATCH_NO_MAX_LEN = 32


# --------------------------------------------------------------------------- 纯工具
def quantize_amount(value: Any) -> Decimal:
    """金额统一两位小数（ROUND_HALF_UP），与 DECIMAL(14,2) 对齐。"""
    return Decimal(value or 0).quantize(AMOUNT_EXP, rounding=ROUND_HALF_UP)


def quantize_price(value: Any) -> Decimal:
    """单价统一四位小数（ROUND_HALF_UP），与 DECIMAL(12,4) 对齐。"""
    return Decimal(value).quantize(PRICE_EXP, rounding=ROUND_HALF_UP)


def resolve_purchase_price(db: Session, sku_id: int, on_date: date) -> Decimal | None:
    """取该 SKU 在 on_date 当时有效的采购价（生效区间命中，取最近生效的一条）。

    Returns:
        Decimal | None：无有效价目时返回 None，由调用方决定报错口径。
    """
    price = db.scalar(
        select(Price.price)
        .where(
            _not_deleted(Price),
            Price.sku_id == int(sku_id),
            Price.price_type == "purchase",
            Price.effective_from <= on_date,
            or_(Price.effective_to.is_(None), Price.effective_to >= on_date),
        )
        .order_by(Price.effective_from.desc(), Price.id.desc())
    )
    return quantize_price(price) if price is not None else None


def _resolve_lines(db: Session, items: Sequence[Any], *, on_date: date) -> list[dict[str, Any]]:
    """请求明细→落库行。

    unit 缺省取 SKU.unit；qty_base 按 convert_factor 换算；单价缺省取当时有效的 purchase 价。
    """
    sku_ids = {int(item.sku_id) for item in items}
    skus = {
        int(sku.id): sku
        for sku in db.scalars(select(Sku).where(Sku.id.in_(sku_ids), _not_deleted(Sku))).all()
    }
    lines: list[dict[str, Any]] = []
    for item in items:
        sku = skus.get(int(item.sku_id))
        if sku is None:
            raise NotFoundError(f"SKU 不存在：{item.sku_id}")
        factor = Decimal(sku.convert_factor)
        if factor <= 0:
            raise BusinessError(f"SKU {sku.id} 的换算因子非法，无法换算基础单位数量")
        qty_unit = quantize_qty(item.qty_unit)
        if qty_unit <= 0:
            raise BusinessError("采购数量必须大于 0")
        if item.unit_price is not None:
            unit_price: Decimal | None = quantize_price(item.unit_price)
        else:
            unit_price = resolve_purchase_price(db, int(sku.id), on_date)
        if unit_price is None or unit_price <= 0:
            raise BusinessError(
                f"SKU {sku.id}（{sku.name}）缺少 {on_date} 有效的采购价："
                "请传 unit_price 或先维护 price(price_type=purchase) 价目"
            )
        lines.append(
            {
                "sku_id": int(sku.id),
                "qty_base": quantize_qty(qty_unit * factor),
                "qty_unit": qty_unit,
                "unit": item.unit or sku.unit,
                "unit_price": unit_price,
            }
        )
    lines.sort(key=lambda line: line["sku_id"])
    return lines


def _canonical_lines(rows: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    """明细规范化：排序 + 定精度 + 转字符串，保证指纹与书写顺序无关。"""
    return sorted(
        [
            str(int(row["sku_id"])),
            str(quantize_qty(row["qty_unit"])),
            str(quantize_qty(row["qty_base"])),
            str(row["unit"]),
            str(quantize_price(row["unit_price"])),
        ]
        for row in rows
    )


def _po_fingerprint(
    supplier_id: int, expected_date: date | None, rows: Sequence[Mapping[str, Any]]
) -> str:
    """采购单请求指纹：供应商 + 预计到货日 + 规范化明细（单价取「缺省解析后」的值）。"""
    return fingerprint_payload(
        {
            "supplier_id": int(supplier_id),
            "expected_date": expected_date,
            "items": _canonical_lines(rows),
        }
    )


# --------------------------------------------------------------------------- 装配投影
def _items_of(db: Session, po_id: int) -> list[PurchaseOrderItem]:
    """取某采购单的全部明细（按 id 升序，落库顺序=请求顺序）。"""
    return list(
        db.scalars(
            select(PurchaseOrderItem)
            .where(PurchaseOrderItem.po_id == po_id)
            .order_by(PurchaseOrderItem.id)
        ).all()
    )


def attach_items(db: Session, orders: Sequence[PurchaseOrder]) -> None:
    """批量装配明细与 SKU 编码/品名（一次查询覆盖整页，避免 N+1）。

    items 不是 ORM 映射列，只是给 schema 投影用的瞬时属性；
    SKU 不过滤软删：历史单据仍要能显示当时的品名。
    """
    ids = [int(order.id) for order in orders]
    rows: list[PurchaseOrderItem] = []
    if ids:
        rows = list(
            db.scalars(
                select(PurchaseOrderItem)
                .where(PurchaseOrderItem.po_id.in_(ids))
                .order_by(PurchaseOrderItem.po_id, PurchaseOrderItem.id)
            ).all()
        )
    sku_ids = {int(row.sku_id) for row in rows}
    skus = (
        {int(sku.id): sku for sku in db.scalars(select(Sku).where(Sku.id.in_(sku_ids))).all()}
        if sku_ids
        else {}
    )
    grouped: dict[int, list[PurchaseOrderItem]] = {}
    for row in rows:
        sku = skus.get(int(row.sku_id))
        row.sku_no = getattr(sku, "sku_no", None)
        row.sku_name = getattr(sku, "name", None)
        grouped.setdefault(int(row.po_id), []).append(row)
    for order in orders:
        order.items = grouped.get(int(order.id), [])


def attach_supplier_names(db: Session, orders: Sequence[PurchaseOrder]) -> None:
    """批量装配供应商名称（一次查询覆盖整页）。"""
    supplier_ids = {int(order.supplier_id) for order in orders}
    names = (
        {
            int(supplier.id): supplier.name
            for supplier in db.scalars(select(Supplier).where(Supplier.id.in_(supplier_ids))).all()
        }
        if supplier_ids
        else {}
    )
    for order in orders:
        order.supplier_name = names.get(int(order.supplier_id))


# --------------------------------------------------------------------------- 查询
def get_purchase_order(db: Session, po_id: int) -> PurchaseOrder:
    """按 id 取采购单（含明细 + SKU/供应商名）；不存在或已软删 → 40400。"""
    order = _load_or_404(db, PurchaseOrder, po_id, "采购单")
    attach_items(db, [order])
    attach_supplier_names(db, [order])
    return order


def list_purchase_orders(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    supplier_id: int | None = None,
) -> PageResult[PurchaseOrder]:
    """采购单分页查询（§8.2 GET /purchase-orders?status=&supplier_id=）。"""
    conditions: list[Any] = [_not_deleted(PurchaseOrder)]
    if status is not None:
        if status not in PO_STATUSES:
            raise BusinessError(f"采购单状态非法：{status}")
        conditions.append(PurchaseOrder.status == status)
    if supplier_id is not None:
        conditions.append(PurchaseOrder.supplier_id == int(supplier_id))
    result = _page_query(
        db,
        PurchaseOrder,
        conditions,
        page=page,
        page_size=page_size,
        order_by=(PurchaseOrder.id.desc(),),
    )
    attach_items(db, result.items)
    attach_supplier_names(db, result.items)
    return result


# --------------------------------------------------------------------------- 建单
def create_purchase_order(
    db: Session,
    payload: PurchaseCreate,
    *,
    operator_id: int | None = None,
    idempotency_key: str | None = None,
) -> PurchaseOrder:
    """创建采购单（draft）：单价缺省取 price 表 purchase 当时价，幂等键防重复建单。

    Raises:
        NotFoundError 40400: 供应商或 SKU 不存在。
        BusinessError 40000: 数量非法 / 缺少有效采购价。
        ConflictError 40900: 幂等键重复但请求体与首次提交不一致。
    """
    supplier = _load_or_404(db, Supplier, int(payload.supplier_id), "供应商")
    # 价格取「预计到货日 / 今天」当时有效的 purchase 价：下单价须可复算（§7.1 价目带生效区间）
    on_date = payload.expected_date or date.today()
    lines = _resolve_lines(db, payload.items, on_date=on_date)
    request_fp = _po_fingerprint(payload.supplier_id, payload.expected_date, lines)
    expect_at = datetime.combine(payload.expected_date, time.min) if payload.expected_date else None

    def build() -> PurchaseOrder:
        order = PurchaseOrder(
            po_no=build_doc_no(
                db,
                model=PurchaseOrder,
                column=PurchaseOrder.po_no,
                prefix=PO_NO_PREFIX,
                on_date=date.today(),
            ),
            supplier_id=int(payload.supplier_id),
            store_id=WAREHOUSE_STORE_ID,
            status=PO_STATUS_DRAFT,
            expect_at=expect_at,
            remark=payload.remark,
            idempotency_key=idempotency_key,
            created_by=operator_id,
            updated_by=operator_id,
        )
        db.add(order)
        db.flush()
        for line in lines:
            db.add(
                PurchaseOrderItem(
                    po_id=order.id,
                    sku_id=line["sku_id"],
                    qty_base=line["qty_base"],
                    qty_unit=line["qty_unit"],
                    unit=line["unit"],
                    price=line["unit_price"],
                    received_qty_base=Decimal("0.000"),
                    created_by=operator_id,
                    updated_by=operator_id,
                )
            )
        db.flush()
        return order

    order = _insert_idempotent(
        db,
        build=build,
        find_existing=lambda: (
            _find_one(db, PurchaseOrder, PurchaseOrder.idempotency_key == idempotency_key)
            if idempotency_key
            else None
        ),
        request_fingerprint=request_fp,
        existing_fingerprint=lambda entity: _po_fingerprint(
            int(entity.supplier_id),
            entity.expect_at.date() if isinstance(entity.expect_at, datetime) else None,
            [
                {
                    "sku_id": row.sku_id,
                    "qty_base": row.qty_base,
                    "qty_unit": row.qty_unit,
                    "unit": row.unit,
                    "unit_price": row.price,
                }
                for row in _items_of(db, int(entity.id))
            ],
        ),
        conflict_message="幂等键重复且采购单内容与首次提交不一致",
    )
    attach_items(db, [order])
    order.supplier_name = supplier.name
    return order


# --------------------------------------------------------------------------- 收货
def _receive_lines(
    order: PurchaseOrder, items: Sequence[PurchaseOrderItem], payload: ReceiveIn
) -> list[dict[str, Any]]:
    """把收货请求解析成逐行收货结果：数量、效期、批次号（结果与明细书写顺序无关）。"""
    by_sku = {int(item.sku_id): item for item in items}
    prefix = payload.batch_no_prefix or order.po_no
    if len(prefix) > BATCH_NO_MAX_LEN - BATCH_SEQ_WIDTH:
        raise BusinessError(
            f"批次号前缀过长（{len(prefix)}）：{BATCH_NO_MAX_LEN} 位上限内需留出 "
            f"{BATCH_SEQ_WIDTH} 位序号"
        )

    resolved: list[dict[str, Any]] = []
    if payload.items:
        seen: set[int] = set()
        for entry in payload.items:
            sku_id = int(entry.sku_id)
            item = by_sku.get(sku_id)
            if item is None:
                raise NotFoundError(f"SKU {sku_id} 不在该采购单明细内")
            if sku_id in seen:
                raise BusinessError(f"收货明细中 SKU 重复：{sku_id}")
            seen.add(sku_id)
            qty = quantize_qty(entry.qty_base)
            if qty <= 0:
                raise BusinessError("收货数量必须大于 0")
            resolved.append(
                {
                    "item": item,
                    "sku_id": sku_id,
                    "qty_base": qty,
                    "expire_at": entry.expire_at or payload.expire_at,
                    "unit_price": entry.unit_price,
                }
            )
    else:
        # items 缺省 = 按明细未收数量整单收货；效期只能来自请求头，缺失即 40000
        if payload.expire_at is None:
            raise BusinessError("整单收货必须指定 expire_at（批次必须有保质期）")
        for item in items:
            remaining = quantize_qty(item.qty_base) - quantize_qty(item.received_qty_base)
            if remaining <= 0:
                continue
            resolved.append(
                {
                    "item": item,
                    "sku_id": int(item.sku_id),
                    "qty_base": quantize_qty(remaining),
                    "expire_at": payload.expire_at,
                    "unit_price": None,
                }
            )
    if not resolved:
        raise ConflictError("该采购单已无可收数量，无需重复收货")
    for line in resolved:
        if line["expire_at"] is None:
            raise BusinessError(f"SKU {line['sku_id']} 缺少保质期（expire_at 必填）")
        # MySQL DATETIME 精确到秒：入库前截掉微秒，避免同批次重收时效期比对假冲突
        line["expire_at"] = line["expire_at"].replace(microsecond=0)
    resolved.sort(key=lambda line: line["sku_id"])
    for seq, line in enumerate(resolved, start=1):
        line["batch_no"] = f"{prefix}{seq:0{BATCH_SEQ_WIDTH}d}"
    return resolved


def _apply_receive(
    db: Session,
    order: PurchaseOrder,
    lines: Sequence[dict[str, Any]],
    *,
    operator_id: int | None,
) -> None:
    """同一事务写结存 + 流水，并累加明细已收数量（「结存有数、流水有据」双轨）。"""
    store_id = int(order.store_id)
    sku_ids = sorted({int(line["sku_id"]) for line in lines})
    batch_nos = sorted({str(line["batch_no"]) for line in lines})
    locked = list(
        db.scalars(
            select(BatchStock)
            .where(
                _not_deleted(BatchStock),
                BatchStock.store_id == store_id,
                BatchStock.sku_id.in_(sku_ids),
                BatchStock.batch_no.in_(batch_nos),
            )
            .order_by(BatchStock.id)
            .with_for_update()
        ).all()
    )
    batches = {(int(row.sku_id), str(row.batch_no)): row for row in locked}
    occurred_at = datetime.now()
    for line in lines:
        sku_id = int(line["sku_id"])
        batch_no = str(line["batch_no"])
        expire_at = line["expire_at"]
        qty = quantize_qty(line["qty_base"])
        batch = batches.get((sku_id, batch_no))
        if batch is None:
            batch = BatchStock(
                store_id=store_id,
                sku_id=sku_id,
                batch_no=batch_no,
                qty_base=Decimal("0.000"),
                expire_at=expire_at,
                version=0,
                created_by=operator_id,
                updated_by=operator_id,
            )
            db.add(batch)
            db.flush()
            batches[(sku_id, batch_no)] = batch
        elif batch.expire_at != expire_at:
            # 批次身份含效期：同批次号不同效期必须换号，避免结存行保质期被静默改写
            raise ConflictError(
                f"批次 {batch_no}（SKU {sku_id}）已存在且保质期不一致，请更换 batch_no_prefix"
            )
        qty_after = quantize_qty(batch.qty_base) + qty
        batch.qty_base = qty_after
        batch.version = int(batch.version or 0) + 1
        batch.updated_by = operator_id
        db.add(
            BatchFlow(
                store_id=store_id,
                sku_id=sku_id,
                batch_no=batch_no,
                flow_type="receive_add",
                qty_change_base=qty,
                qty_after_base=qty_after,
                expire_at=expire_at,
                doc_type="purchase_order",
                doc_id=int(order.id),
                doc_no=order.po_no,
                doc_item_id=int(line["item"].id),
                operate_by=int(operator_id or 0),
                occurred_at=occurred_at,
                remark=f"采购收货入总部仓（{order.po_no}）",
            )
        )
        item = line["item"]
        item.received_qty_base = quantize_qty(item.received_qty_base) + qty
        if line.get("unit_price") is not None:
            item.price = quantize_price(line["unit_price"])
        item.updated_by = operator_id
    db.flush()


def receive_purchase_order(
    db: Session,
    po_id: int,
    payload: ReceiveIn | None = None,
    *,
    operator_id: int | None = None,
    idempotency_key: str | None = None,
) -> PurchaseOrder:
    """收货：同一事务写 batch_stock（结存）+ batch_flow（receive_add 流水），推进状态机。

    - 防重：采购单行锁 + 状态机（已收货 → 40900）+ uk_flow_source 唯一索引三重兜底；
    - 同键重放：请求头 Idempotency-Key 与单据已记录的键一致时返回首次收货结果（§8.1）；
      该列优先记录建单幂等键，仅在建单未带键（为空）时回填本次收货键；
    - 全量收满（默认路径）→ status=draft/submitted→received；显式部分收货保持 draft，
      余量记入 purchase_order_item.received_qty_base，可再次收货补齐（§7.2「支持分批收货」）；
    - 批次号 = batch_no_prefix（缺省采购单号）+ 两位序号，按 SKU 升序编号，结果可复现。

    Raises:
        NotFoundError 40400: 采购单不存在 / 收货 SKU 不在本单明细内。
        BusinessError 40000: 数量非正 / 缺 batch_no 前缀过长 / 缺少保质期 expire_at。
        ConflictError 40900: 已收货重复收货 / 状态不允许 / 同批次号效期不一致 / 无可收数量。
    """
    order = _load_or_404(db, PurchaseOrder, po_id, "采购单")
    # 行锁：并发重复收货串行化，后到者看到的状态已是 received → 40900，杜绝重复入账
    locked = db.scalar(
        select(PurchaseOrder)
        .where(PurchaseOrder.id == order.id, _not_deleted(PurchaseOrder))
        .with_for_update()
    )
    if locked is not None:
        order = locked
    if order.status == PO_STATUS_RECEIVED:
        if idempotency_key and order.idempotency_key == idempotency_key:
            attach_items(db, [order])
            attach_supplier_names(db, [order])
            return order
        raise ConflictError("采购单已收货，不能重复收货（重复入账会破坏结存与流水恒等式）")
    if order.status not in PO_RECEIVABLE_STATUSES:
        raise ConflictError(f"采购单当前状态为 {order.status}，不能收货")

    # 明细行一并加锁：同一采购单的已收数量只允许串行累加
    items = list(
        db.scalars(
            select(PurchaseOrderItem)
            .where(PurchaseOrderItem.po_id == order.id)
            .order_by(PurchaseOrderItem.id)
            .with_for_update()
        ).all()
    )
    if not items:
        raise NotFoundError("采购单没有明细，无法收货")

    lines = _receive_lines(order, items, payload or ReceiveIn())
    _apply_receive(db, order, lines, operator_id=operator_id)

    fully_received = all(
        quantize_qty(item.received_qty_base) >= quantize_qty(item.qty_base) for item in items
    )
    if fully_received:
        order.status = PO_STATUS_RECEIVED
    if idempotency_key and not order.idempotency_key:
        order.idempotency_key = idempotency_key
    order.updated_by = operator_id
    order.version = int(order.version or 0) + 1
    db.flush()

    attach_items(db, [order])
    attach_supplier_names(db, [order])
    return order
