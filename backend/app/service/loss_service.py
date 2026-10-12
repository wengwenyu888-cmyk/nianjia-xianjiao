"""报损服务（§7.5 模型 + §8.2 报损组端点）。

分层铁律：本层是唯一的事务边界与业务判定处；不感知 HTTP，只抛 BusinessError 子类。

流程：门店提交报损（draft）→ 总部审批（approved）才动库存：
- 审批在同一事务内完成「扣减 batch_stock + 写 batch_flow(loss_sub / count_adjust)」，
  两者缺一不可（§7.5 loss 注释：结存有数、流水有据）；
- 报损单带批次时只扣该批次；不带批次时按 expire_at 升序 FIFO 跨批次扣减（临期先出），
  每个批次各写一行流水，流水唯一索引 uk_flow_source 兜底防重复入账；
- 库存不足 → 40900（不产生半扣状态：先算总量后扣减）；
- 审批是状态推进，天然幂等（已 approved 直接返回首次结果），不占用 idempotency_key
  （该列语义是「提交请求幂等键」）。

数据范围：门店账号只能为本店提交（跨店 40300）；总部账号必须显式指定 store_id。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    BusinessError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.model.base import SOFT_DELETE_SENTINEL
from app.model.inventory import BatchFlow, BatchStock
from app.model.loss import Loss
from app.model.store import Sku, Store
from app.schema.loss import LossCreate
from app.service.delivery_service import Actor
from app.service.store_service import PageResult, fingerprint_payload

# 单据号前缀：BS + YYYYMMDD + 4 位顺序号
LOSS_NO_PREFIX = "BS"
# 单据号并发撞车后的重试次数（唯一索引 uk_loss_no 兜底）
MAX_DOC_NO_ATTEMPTS = 3
# 报损类型 → 流水动作（§7.5：flow_type = loss_sub 或 count_adjust）
LOSS_FLOW_TYPE: dict[str, str] = {"count_diff": "count_adjust"}
ZERO = Decimal("0")


# --------------------------------------------------------------------------- 内部工具
def _not_deleted(model: Any) -> Any:
    return model.deleted_at == SOFT_DELETE_SENTINEL


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


def _next_doc_no(db: Session, column: Any, *, prefix: str, moment: datetime) -> str:
    """生成单据号：前缀 + YYYYMMDD + 当日顺序号；并发撞号由唯一索引兜底并重试。"""
    head = f"{prefix}{moment:%Y%m%d}"
    last = db.scalar(select(func.max(column)).where(column.like(f"{head}%")))
    suffix = str(last)[len(head) :] if last else ""
    seq = int(suffix) + 1 if suffix.isdigit() else 1
    return f"{head}{seq:04d}"


def _decimal_token(value: Decimal | None) -> str | None:
    """Decimal 归一化：去尾零后转字符串，避免 5 / 5.000 被判成两个请求体。"""
    return None if value is None else str(Decimal(value).normalize())


def _fingerprint(values: dict[str, Any]) -> str:
    return fingerprint_payload(values)


def _loss_values(
    *,
    store_id: int,
    sku_id: int,
    batch_no: str | None,
    qty_base: Decimal,
    type_: str,
    reason: str | None,
) -> dict[str, Any]:
    """幂等指纹入参（请求侧与实体侧共用同一形状）。"""
    return {
        "store_id": store_id,
        "sku_id": sku_id,
        "batch_no": batch_no,
        "qty_base": _decimal_token(qty_base),
        "type": type_,
        "reason": reason,
    }


def resolve_store_id(payload: LossCreate, actor: Actor | None) -> int:
    """门店归属判定：门店账号强制本店（跨店 40300）；总部账号必须显式传 store_id。"""
    if actor is not None and actor.store_id is not None:
        if payload.store_id is not None and payload.store_id != actor.store_id:
            raise PermissionDeniedError("门店账号只能为本店提交报损")
        return actor.store_id
    if payload.store_id is None:
        raise BusinessError("总部账号提交报损必须指定 store_id")
    return payload.store_id


def resolve_list_store_scope(actor: Actor | None, store_id: int | None) -> int | None:
    """列表数据范围：门店账号强制本店（显式请求他店 → 40300），总部账号按入参。"""
    if actor is None or actor.store_id is None:
        return store_id
    if store_id is not None and store_id != actor.store_id:
        raise PermissionDeniedError("门店账号只能查看本店的报损单")
    return actor.store_id


def _require_store(db: Session, store_id: int) -> Store:
    store = db.scalar(select(Store).where(_not_deleted(Store), Store.id == store_id))
    if store is None:
        raise NotFoundError("门店不存在")
    return store


def _require_sku(db: Session, sku_id: int) -> Sku:
    sku = db.scalar(select(Sku).where(_not_deleted(Sku), Sku.id == sku_id))
    if sku is None:
        raise NotFoundError("SKU 不存在")
    return sku


# --------------------------------------------------------------------------- 查询
def get_loss(db: Session, loss_id: int) -> Loss:
    """按 id 查报损单；不存在或已软删 → 40400。"""
    loss = db.scalar(select(Loss).where(_not_deleted(Loss), Loss.id == loss_id))
    if loss is None:
        raise NotFoundError("报损单不存在")
    return loss


def list_losses(
    db: Session,
    *,
    store_id: int | None = None,
    status: str | None = None,
    type_: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult[Loss]:
    """GET /losses?store_id=&status=：报损分页查询（仅未软删数据）。"""
    conditions: list[Any] = [_not_deleted(Loss)]
    if store_id is not None:
        conditions.append(Loss.store_id == store_id)
    if status is not None:
        conditions.append(Loss.status == status)
    if type_ is not None:
        conditions.append(Loss.type == type_)
    return _page_query(
        db,
        Loss,
        conditions,
        page=page,
        page_size=page_size,
        order_by=(Loss.id.desc(),),
    )


# --------------------------------------------------------------------------- 提交
def create_loss(
    db: Session,
    payload: LossCreate,
    *,
    actor: Actor | None = None,
    operator_id: int | None = None,
    idempotency_key: str | None = None,
    now: datetime | None = None,
) -> Loss:
    """POST /losses（门店提交报损）：落 draft 单，不动库存；审批通过才扣减。

    幂等：Idempotency-Key 命中且请求体一致 → 返回首次结果；异体 → 40900。
    """
    moment = now or datetime.now()
    operator = operator_id if operator_id is not None else (actor.user_id if actor else None)
    store_id = resolve_store_id(payload, actor)
    _require_store(db, store_id)
    _require_sku(db, payload.sku_id)
    values = _loss_values(
        store_id=store_id,
        sku_id=payload.sku_id,
        batch_no=payload.batch_no,
        qty_base=payload.qty_base,
        type_=payload.type,
        reason=payload.reason,
    )
    request_fp = _fingerprint(values)

    if idempotency_key:
        existing = db.scalar(
            select(Loss).where(_not_deleted(Loss), Loss.idempotency_key == idempotency_key)
        )
        if existing is not None:
            if _fingerprint(_stored_values(existing)) != request_fp:
                raise ConflictError("幂等键重复且请求内容与首次提交不一致")
            return existing

    for attempt in range(MAX_DOC_NO_ATTEMPTS):
        loss = Loss(
            loss_no=_next_doc_no(db, Loss.loss_no, prefix=LOSS_NO_PREFIX, moment=moment),
            store_id=store_id,
            sku_id=payload.sku_id,
            batch_no=payload.batch_no,
            qty_base=payload.qty_base,
            type=payload.type,
            reason=payload.reason,
            status="draft",
            idempotency_key=idempotency_key,
            created_by=operator,
            updated_by=operator,
        )
        try:
            with db.begin_nested():
                db.add(loss)
                db.flush()
        except IntegrityError as exc:
            found = (
                db.scalar(
                    select(Loss).where(_not_deleted(Loss), Loss.idempotency_key == idempotency_key)
                )
                if idempotency_key
                else None
            )
            if found is not None:
                if _fingerprint(_stored_values(found)) != request_fp:
                    raise ConflictError("幂等键重复且请求内容与首次提交不一致") from exc
                return found
            if attempt == MAX_DOC_NO_ATTEMPTS - 1:
                raise ConflictError("报损单号生成冲突，请重试") from exc
            continue
        return loss
    raise ConflictError("报损单号生成冲突，请重试")  # pragma: no cover（循环内必返回或抛错）


def _stored_values(loss: Loss) -> dict[str, Any]:
    """实体侧指纹：与请求侧同字段、同归一化规则。"""
    return _loss_values(
        store_id=loss.store_id,
        sku_id=loss.sku_id,
        batch_no=loss.batch_no,
        qty_base=loss.qty_base,
        type_=loss.type,
        reason=loss.reason,
    )


# --------------------------------------------------------------------------- 审批
def _lock_batches(db: Session, loss: Loss) -> list[BatchStock]:
    """锁批次结存行：带批次只锁该批次，否则按 expire_at 升序 FIFO 锁全店该 SKU 批次。"""
    conditions: list[Any] = [
        _not_deleted(BatchStock),
        BatchStock.store_id == loss.store_id,
        BatchStock.sku_id == loss.sku_id,
    ]
    if loss.batch_no:
        conditions.append(BatchStock.batch_no == loss.batch_no)
    stmt = (
        select(BatchStock)
        .where(*conditions)
        .order_by(BatchStock.expire_at.asc(), BatchStock.id.asc())
        .with_for_update()
    )
    return list(db.scalars(stmt).all())


def approve_loss(
    db: Session,
    loss_id: int,
    *,
    operator_id: int | None = None,
    now: datetime | None = None,
) -> Loss:
    """POST /losses/{id}/approve（总部审批）：draft → approved。

    同一事务内扣减门店批次库存并写 batch_flow（loss_sub / count_adjust）；库存不足 → 40900；
    已 approved 直接返回首次结果（幂等）。
    """
    moment = now or datetime.now()
    if operator_id is None:
        raise BusinessError("审批报损需要操作人身份")
    loss = get_loss(db, loss_id)
    if loss.status == "approved":
        return loss
    if loss.status != "draft":
        raise ConflictError(f"报损单状态 {loss.status} 不能审批")

    stocks = _lock_batches(db, loss)
    available = sum((stock.qty_base for stock in stocks), ZERO)
    if available < loss.qty_base:
        scope = f"批次 {loss.batch_no}" if loss.batch_no else "门店该 SKU 全部批次"
        raise ConflictError(f"库存不足：{scope}可用 {available}，报损 {loss.qty_base}")

    flow_type = LOSS_FLOW_TYPE.get(loss.type, "loss_sub")
    remaining = loss.qty_base
    for stock in stocks:
        if remaining <= 0:
            break
        take = min(remaining, stock.qty_base)
        if take <= 0:
            continue
        stock.qty_base = stock.qty_base - take
        stock.version = int(stock.version or 0) + 1
        stock.updated_by = operator_id
        db.add(
            BatchFlow(
                store_id=loss.store_id,
                sku_id=loss.sku_id,
                batch_no=stock.batch_no,
                flow_type=flow_type,
                qty_change_base=-take,
                qty_after_base=stock.qty_base,
                expire_at=stock.expire_at,
                doc_type="loss",
                doc_id=loss.id,
                doc_no=loss.loss_no,
                doc_item_id=loss.id,
                operate_by=operator_id,
                occurred_at=moment,
                remark=loss.reason or "报损审批扣减",
            )
        )
        remaining = remaining - take

    loss.status = "approved"
    loss.approved_by = operator_id
    loss.approved_at = moment
    loss.updated_by = operator_id
    db.flush()
    return loss
