"""要货服务（§7.3 模型 + §8.2「要货」组端点）。

分层铁律：状态机流转、幂等判定、事务边界只在本层；api 只做协议，不碰 model。

状态机（§7.3 order_head.status）：draft→confirmed→merged→cancelled
  - draft→confirmed：店长确认（confirm_order），落 confirm_by / confirm_at；
  - draft→cancelled：确认前可取消（cancel_order）；
  - confirmed→merged：不在本模块流转，由汇总环节（summary_service.generate_summary）批量推进。

幂等（§8.1）：order_head.uk_idem(idempotency_key, deleted_at) + 请求指纹——
同一 Idempotency-Key 重复提交返回首次结果；键相同但请求体（门店 / 配送日 / 规范化明细）
不一致返回 40900。状态流转类接口以「已在目标状态即视为重放」实现重试安全。

数据范围（§8.1）：store_id_scope 非空（门店账号）时只能操作/查询本店数据，越权 40300。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError, ConflictError, NotFoundError, PermissionDeniedError
from app.model.order import OrderHead, OrderItem
from app.model.store import Sku, Store
from app.schema.order import OrderCreate, OrderUpdate
from app.service.store_service import (
    PageResult,
    _find_one,
    _insert_idempotent,
    _load_or_404,
    _not_deleted,
    _page_query,
    check_optimistic_lock,
    fingerprint_payload,
)

# --------------------------------------------------------------------------- 常量
ORDER_NO_PREFIX = "DD"
# 状态机值域与 §7.3 order_head.status 一致；流转只在本层发生（前端不可直接改状态）
ORDER_STATUSES: tuple[str, ...] = ("draft", "confirmed", "merged", "cancelled")
ORDER_EDITABLE_STATUSES: tuple[str, ...] = ("draft",)
ORDER_CONFIRM_FROM: tuple[str, ...] = ("draft",)
ORDER_CANCEL_FROM: tuple[str, ...] = ("draft",)
ORDER_SOURCES: tuple[str, ...] = ("manual", "agent")
# 数量口径三位小数，与 DECIMAL(14,3) 对齐：避免指纹漂移与数据库四舍五入不一致
QTY_EXP = Decimal("0.001")


# --------------------------------------------------------------------------- 纯工具
def quantize_qty(value: Any) -> Decimal:
    """数量统一三位小数（ROUND_HALF_UP），全项目共用同一口径。"""
    return Decimal(value).quantize(QTY_EXP, rounding=ROUND_HALF_UP)


def build_doc_no(
    db: Session,
    *,
    model: Any,
    column: Any,
    prefix: str,
    on_date: date,
    width: int = 4,
) -> str:
    """单据号 = 前缀 + 业务日期 + 4 位序号（如 DD202610130001）。

    序号取当日现存最大号 +1；并发下由唯一索引 uk_*_no 兜底（撞号即 40900，重试得新号）。
    汇总/分拣单据号复用本函数（订单、汇总、分拣同一编号规则）。
    """
    head = f"{prefix}{on_date:%Y%m%d}"
    last = db.scalar(select(func.max(column)).where(column.like(f"{head}%")))
    seq = int(str(last)[len(head) :]) + 1 if last else 1
    return f"{head}{seq:0{width}d}"


def _canonical_lines(rows: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    """明细规范化：排序 + 数量定精度 + 转字符串，保证指纹与书写顺序无关。"""
    return sorted(
        [
            str(int(row["sku_id"])),
            str(quantize_qty(row["qty_base"])),
            str(quantize_qty(row["qty_unit"])),
            str(row["unit"]),
        ]
        for row in rows
    )


def _order_fingerprint(store_id: int, require_date: date, rows: Sequence[Mapping[str, Any]]) -> str:
    """要货单请求指纹：门店 + 配送日 + 规范化明细。"""
    return fingerprint_payload(
        {"store_id": int(store_id), "require_date": require_date, "items": _canonical_lines(rows)}
    )


def _resolve_lines(db: Session, items: Sequence[Any]) -> list[dict[str, Any]]:
    """把请求明细换算成落库行：unit 缺省取 SKU.unit，qty_base 缺省按 convert_factor 换算。"""
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
        qty_base = (
            quantize_qty(item.qty_base)
            if item.qty_base is not None
            else quantize_qty(qty_unit * factor)
        )
        if qty_unit <= 0 or qty_base <= 0:
            raise BusinessError("要货数量必须大于 0")
        lines.append(
            {
                "sku_id": int(sku.id),
                "qty_base": qty_base,
                "qty_unit": qty_unit,
                "unit": item.unit or sku.unit,
            }
        )
    return lines


def _items_of(db: Session, order_id: int) -> list[OrderItem]:
    return list(
        db.scalars(
            select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.id)
        ).all()
    )


def attach_items(db: Session, orders: Sequence[OrderHead]) -> None:
    """批量装配明细投影字段 items（一次查询覆盖整页，避免逐单 N+1）。

    items 不是 ORM 映射列，只是给 schema 投影用的瞬时属性（setattr 以避开静态检查噪音）。
    """
    ids = [int(order.id) for order in orders]
    grouped: dict[int, list[OrderItem]] = {}
    if ids:
        rows = db.scalars(
            select(OrderItem)
            .where(OrderItem.order_id.in_(ids))
            .order_by(OrderItem.order_id, OrderItem.id)
        ).all()
        for row in rows:
            grouped.setdefault(int(row.order_id), []).append(row)
    for order in orders:
        order.items = grouped.get(int(order.id), [])


# --------------------------------------------------------------------------- 查询
def get_order(db: Session, order_id: int, *, store_id_scope: int | None = None) -> OrderHead:
    """按 id 取要货单（含明细）；不存在 40400，跨店 40300。"""
    order = _load_or_404(db, OrderHead, order_id, "要货单")
    if store_id_scope is not None and int(order.store_id) != int(store_id_scope):
        raise PermissionDeniedError("门店账号只能访问本店要货单")
    attach_items(db, [order])
    return order


def list_orders(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    store_id: int | None = None,
    require_date: date | None = None,
    status: str | None = None,
    store_id_scope: int | None = None,
) -> PageResult[OrderHead]:
    """要货单分页查询：store_id / require_date / status 过滤（§8.2 GET /orders）。

    门店账号（store_id_scope 非空）只能查本店：显式传入他店 store_id 直接 40300，
    未传则强制注入本店条件。
    """
    if store_id_scope is not None:
        if store_id is not None and int(store_id) != int(store_id_scope):
            raise PermissionDeniedError("门店账号只能查询本店要货单")
        store_id = int(store_id_scope)
    conditions: list[Any] = [_not_deleted(OrderHead)]
    if store_id is not None:
        conditions.append(OrderHead.store_id == int(store_id))
    if require_date is not None:
        conditions.append(OrderHead.require_date == require_date)
    if status is not None:
        if status not in ORDER_STATUSES:
            raise BusinessError(f"要货单状态非法：{status}")
        conditions.append(OrderHead.status == status)
    result = _page_query(
        db,
        OrderHead,
        conditions,
        page=page,
        page_size=page_size,
        order_by=(OrderHead.require_date.desc(), OrderHead.id.desc()),
    )
    attach_items(db, result.items)
    return result


# --------------------------------------------------------------------------- 写
def create_order(
    db: Session,
    payload: OrderCreate,
    *,
    store_id_scope: int | None = None,
    operator_id: int | None = None,
    idempotency_key: str | None = None,
    source: str = "manual",
    agent_suggestion_id: int | None = None,
) -> OrderHead:
    """创建要货单（draft）。

    source / agent_suggestion_id 为内部参数：智能体采纳走同一条创建路径并留痕回指，
    对外端点始终使用默认值（source=manual）。

    Raises:
        PermissionDeniedError 40300: 门店账号为他人门店建单。
        NotFoundError 40400: 门店或 SKU 不存在。
        ConflictError 40900: 幂等键重复但请求体不一致。
    """
    store_id = int(payload.store_id) if payload.store_id is not None else store_id_scope
    if store_id is None:
        raise BusinessError("总部账号创建要货单时必须指定 store_id")
    if store_id_scope is not None and store_id != int(store_id_scope):
        raise PermissionDeniedError("门店账号只能为本店创建要货单")
    if source not in ORDER_SOURCES:
        raise BusinessError(f"要货单来源非法：{source}")
    _load_or_404(db, Store, store_id, "门店")
    lines = _resolve_lines(db, payload.items)
    request_fp = _order_fingerprint(store_id, payload.require_date, lines)

    def build() -> OrderHead:
        order = OrderHead(
            order_no=build_doc_no(
                db,
                model=OrderHead,
                column=OrderHead.order_no,
                prefix=ORDER_NO_PREFIX,
                on_date=payload.require_date,
            ),
            store_id=store_id,
            require_date=payload.require_date,
            status="draft",
            source=source,
            agent_suggestion_id=agent_suggestion_id,
            idempotency_key=idempotency_key,
            created_by=operator_id,
            updated_by=operator_id,
        )
        db.add(order)
        db.flush()
        for line in lines:
            db.add(
                OrderItem(order_id=order.id, created_by=operator_id, updated_by=operator_id, **line)
            )
        db.flush()
        return order

    order = _insert_idempotent(
        db,
        build=build,
        find_existing=lambda: (
            _find_one(db, OrderHead, OrderHead.idempotency_key == idempotency_key)
            if idempotency_key
            else None
        ),
        request_fingerprint=request_fp,
        existing_fingerprint=lambda entity: _order_fingerprint(
            int(entity.store_id),
            entity.require_date,
            [
                {
                    "sku_id": row.sku_id,
                    "qty_base": row.qty_base,
                    "qty_unit": row.qty_unit,
                    "unit": row.unit,
                }
                for row in _items_of(db, int(entity.id))
            ],
        ),
        conflict_message="幂等键重复且要货单内容与首次提交不一致",
    )
    attach_items(db, [order])
    return order


def update_order(
    db: Session,
    order_id: int,
    payload: OrderUpdate,
    *,
    store_id_scope: int | None = None,
    operator_id: int | None = None,
) -> OrderHead:
    """修改草稿明细：仅 draft 可改；items 传入即整单覆盖（order_item 无软删列，物理替换）。"""
    order = get_order(db, order_id, store_id_scope=store_id_scope)
    if order.status not in ORDER_EDITABLE_STATUSES:
        raise ConflictError(f"要货单当前状态为 {order.status}，仅草稿可修改明细")
    check_optimistic_lock(order, payload.version, resource="要货单")
    if payload.require_date is not None:
        order.require_date = payload.require_date
    if payload.items is not None:
        lines = _resolve_lines(db, payload.items)
        db.execute(delete(OrderItem).where(OrderItem.order_id == order.id))
        for line in lines:
            db.add(
                OrderItem(order_id=order.id, created_by=operator_id, updated_by=operator_id, **line)
            )
    order.version = int(order.version or 0) + 1
    order.updated_by = operator_id
    db.flush()
    attach_items(db, [order])
    return order


def confirm_order(
    db: Session, order_id: int, *, store_id_scope: int | None = None, operator_id: int | None = None
) -> OrderHead:
    """店长确认：draft→confirmed，落 confirm_by / confirm_at。

    已在 confirmed（重试重放）返回当前结果；merged / cancelled 属非法流转 → 40900。
    """
    order = get_order(db, order_id, store_id_scope=store_id_scope)
    if order.status == "confirmed":
        return order
    if order.status not in ORDER_CONFIRM_FROM:
        raise ConflictError(f"要货单当前状态为 {order.status}，不能确认")
    if not _items_of(db, int(order.id)):
        raise ConflictError("要货单没有明细，不能确认")
    order.status = "confirmed"
    order.confirm_by = operator_id
    order.confirm_at = datetime.now()
    order.version = int(order.version or 0) + 1
    order.updated_by = operator_id
    db.flush()
    return order


def cancel_order(
    db: Session, order_id: int, *, store_id_scope: int | None = None, operator_id: int | None = None
) -> OrderHead:
    """取消要货单：仅 confirmed 前（draft）可取消；已取消视为重放返回当前结果。"""
    order = get_order(db, order_id, store_id_scope=store_id_scope)
    if order.status == "cancelled":
        return order
    if order.status not in ORDER_CANCEL_FROM:
        raise ConflictError(f"要货单当前状态为 {order.status}，确认后不可取消")
    order.status = "cancelled"
    order.version = int(order.version or 0) + 1
    order.updated_by = operator_id
    db.flush()
    return order
