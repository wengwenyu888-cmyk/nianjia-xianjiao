"""配送与签收服务（§7.4 模型 + §8.2 配送签收组端点）。

分层铁律：本层是唯一的事务边界与业务判定处；不感知 HTTP，只抛 BusinessError 子类。

状态机（只在本层流转，§7.4 delivery 注释）：
    loaded --depart--> on_way --sign--> signed / partial / rejected（终态）
非法流转（含重复签收、未发车即签收）一律 40900。

幂等（§8.1）：写接口按 Idempotency-Key 落 delivery.idempotency_key（uk_idem 兜底）；
同键同体返回首次结果，同键异体 40900。签收单无软删，uk_idem 只含 idempotency_key，
且 uk_delivery 强制 1:1：同一配送单重复签收按「重放」处理（明细一致返回首次结果）。

数据范围（§8.1）：门店账号（user.store_id 非空）只能看/签本店配送单；
纯司机（有 driver 角色且无 admin/ops）只能看/发/签自己的车；跨范围一律 40300。

签收后的库存落定（§7.4 sign 注释：「签收后在途落定为门店库存」，服务层事务：
改 batch_stock + 写 batch_flow）：门店批次结存 += 实收量，同一事务写
batch_flow(flow_type=receive_add, doc_type=other, doc_no=配送单号)。约定前提是分拣只扣
总部仓（store_id=0），若分拣环节已把货落入门店仓则会重复计入——集成前需对齐该点。
可用 SIGN_CREDIT_STORE_STOCK 开关关闭该行为。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError, ConflictError, NotFoundError, PermissionDeniedError
from app.model.base import SOFT_DELETE_SENTINEL
from app.model.delivery import Delivery, DeliveryItem, Sign, SignItem
from app.model.inventory import BatchFlow, BatchStock
from app.model.store import Sku, Store
from app.model.summary import Pick, PickItem
from app.schema.delivery import (
    DeliveryCreate,
    SignIn,
)
from app.service.store_service import PageResult, fingerprint_payload

# 单据号前缀（配送单）：PS + YYYYMMDD + 4 位顺序号，总长 ≤ 32
DELIVERY_NO_PREFIX = "PS"
# 单据号并发撞车后的重试次数（唯一索引 uk_delivery_no 兜底）
MAX_DOC_NO_ATTEMPTS = 3
# 总部仓在 batch_stock.store_id 中的约定值（§7.2 BatchStock.store_id 注释）
HQ_STORE_ID = 0
# 签收是否把实收量落定为门店批次库存（§7.4 sign 注释）；关闭后签收只写 sign/sign_item
SIGN_CREDIT_STORE_STOCK = True
# 拥有总部视角的角色：这类账号不受「司机只看自己任务」约束
HQ_ROLES = frozenset({"admin", "ops"})
# 签收状态（sign.status）→ 配送单状态（delivery.status）
SIGN_TO_DELIVERY_STATUS: dict[str, str] = {
    "full": "signed",
    "partial": "partial",
    "reject": "rejected",
}
# 配送单状态机（§7.4）：loaded→on_way→signed/partial/rejected，后三者是终态
DELIVERY_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "loaded": ("on_way",),
    "on_way": ("signed", "partial", "rejected"),
    "signed": (),
    "partial": (),
    "rejected": (),
}


@dataclass(frozen=True)
class Actor:
    """调用者身份（数据范围判定用）：api 层由 CurrentUser 装配后传入。"""

    user_id: int | None = None
    store_id: int | None = None
    roles: frozenset[str] = frozenset()

    @property
    def is_driver_scoped(self) -> bool:
        """纯司机（含司机角色且不含 admin/ops）：只能操作自己名下的配送任务。"""
        return "driver" in self.roles and not (self.roles & HQ_ROLES)


@dataclass(frozen=True)
class SignDetail:
    """签收单详情聚合：签收单 + 明细 + 关联配送单（api 层据此装配 SignOut）。"""

    sign: Sign
    items: list[SignItem]
    delivery: Delivery


# --------------------------------------------------------------------------- 内部工具
def _not_deleted(model: Any) -> Any:
    return model.deleted_at == SOFT_DELETE_SENTINEL


def _decimal_token(value: Decimal | None) -> str | None:
    """Decimal 归一化：去尾零后转字符串，避免 5 / 5.000 被判成两个请求体。"""
    return None if value is None else str(Decimal(value).normalize())


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


def _load_or_404(db: Session, model: Any, entity_id: int, label: str) -> Any:
    entity = db.scalar(select(model).where(_not_deleted(model), model.id == entity_id))
    if entity is None:
        raise NotFoundError(f"{label}不存在")
    return entity


def _load_delivery(db: Session, delivery_id: int) -> Delivery:
    return _load_or_404(db, Delivery, delivery_id, "配送单")


def _load_items(db: Session, delivery_id: int) -> list[DeliveryItem]:
    stmt = (
        select(DeliveryItem)
        .where(DeliveryItem.delivery_id == delivery_id)
        .order_by(DeliveryItem.id.asc())
    )
    return list(db.scalars(stmt).all())


def _find_by_idempotency_key(db: Session, key: str | None) -> Delivery | None:
    if not key:
        return None
    return db.scalar(
        select(Delivery).where(_not_deleted(Delivery), Delivery.idempotency_key == key)
    )


def _find_sign_by_delivery(db: Session, delivery_id: int) -> Sign | None:
    return db.scalar(select(Sign).where(Sign.delivery_id == delivery_id))


def _find_sign_by_key(db: Session, key: str | None) -> Sign | None:
    if not key:
        return None
    return db.scalar(select(Sign).where(Sign.idempotency_key == key))


# --------------------------------------------------------------------------- 数据范围
def assert_can_view(delivery: Delivery, actor: Actor | None) -> None:
    """可见性：门店账号限本店；纯司机限本人任务；否则 40300。"""
    if actor is None:
        return
    if actor.store_id is not None and delivery.store_id != actor.store_id:
        raise PermissionDeniedError("只能查看本店的配送单")
    if actor.is_driver_scoped and delivery.driver_id != actor.user_id:
        raise PermissionDeniedError("司机只能查看自己的配送任务")


def assert_can_depart(delivery: Delivery, actor: Actor | None) -> None:
    """发车：司机只能发自己的车；门店账号不允许发车（无 delivery:depart）。"""
    if actor is None:
        return
    if actor.is_driver_scoped and delivery.driver_id != actor.user_id:
        raise PermissionDeniedError("司机只能发起自己配送单的发车")
    if actor.store_id is not None:
        raise PermissionDeniedError("门店账号不能执行发车操作")


def assert_can_sign(delivery: Delivery, actor: Actor | None) -> None:
    """签收：门店账号只能签本店；纯司机只能签自己的车。"""
    if actor is None:
        return
    if actor.store_id is not None and delivery.store_id != actor.store_id:
        raise PermissionDeniedError("只能签收本店的配送单")
    if actor.is_driver_scoped and delivery.driver_id != actor.user_id:
        raise PermissionDeniedError("司机只能签收自己的配送任务")


# --------------------------------------------------------------------------- 组装
def _item_rows(item_values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """明细行归一化：字段裁剪 + 数量去尾零 + 按 (sku,batch,pick_item) 排序。"""
    rows = [
        {
            "pick_item_id": row["pick_item_id"],
            "sku_id": row["sku_id"],
            "batch_no": row["batch_no"],
            "qty_base": _decimal_token(row["qty_base"]),
        }
        for row in item_values
    ]
    return sorted(rows, key=lambda row: (row["sku_id"], row["batch_no"], row["pick_item_id"] or 0))


def _delivery_request_values(
    payload: DeliveryCreate, item_values: Sequence[dict[str, Any]]
) -> dict:
    """幂等指纹入参：与实体侧同字段、同归一化规则。"""
    return {
        "summary_id": payload.summary_id,
        "store_id": payload.store_id,
        "require_date": payload.require_date,
        "driver_id": payload.driver_id,
        "plate_no": payload.plate_no,
        "items": _item_rows(item_values),
    }


def _delivery_stored_values(db: Session, delivery: Delivery) -> dict:
    """实体侧指纹：从已落库的明细还原同一形状。"""
    rows = db.execute(
        select(
            DeliveryItem.pick_item_id,
            DeliveryItem.sku_id,
            DeliveryItem.batch_no,
            DeliveryItem.qty_base,
        ).where(DeliveryItem.delivery_id == delivery.id)
    ).all()
    item_values = [
        {
            "pick_item_id": row[0],
            "sku_id": row[1],
            "batch_no": row[2],
            "qty_base": row[3],
        }
        for row in rows
    ]
    return {
        "summary_id": delivery.summary_id,
        "store_id": delivery.store_id,
        "require_date": delivery.require_date,
        "driver_id": delivery.driver_id,
        "plate_no": delivery.plate_no,
        "items": _item_rows(item_values),
    }


def _resolve_items(db: Session, payload: DeliveryCreate) -> list[dict[str, Any]]:
    """装车明细：显式传入则校验来源分拣明细，缺省按 (summary_id, store_id) 派生。"""
    if payload.items:
        values: list[dict[str, Any]] = []
        seen: set[tuple[int, str]] = set()
        for item in payload.items:
            key = (item.sku_id, item.batch_no)
            if key in seen:
                raise BusinessError(f"装车明细重复：sku_id={key[0]}, batch_no={key[1]}")
            seen.add(key)
            if item.pick_item_id is not None:
                _assert_pick_item(db, payload, item.pick_item_id, item.sku_id, item.batch_no)
            values.append(
                {
                    "pick_item_id": item.pick_item_id,
                    "sku_id": item.sku_id,
                    "batch_no": item.batch_no,
                    "qty_base": item.qty_base,
                }
            )
        return values

    pick_ids = select(Pick.id).where(
        _not_deleted(Pick),
        Pick.summary_id == payload.summary_id,
        Pick.store_id == payload.store_id,
        Pick.status != "cancelled",
    )
    rows = list(
        db.scalars(
            select(PickItem).where(PickItem.pick_id.in_(pick_ids)).order_by(PickItem.id)
        ).all()
    )
    if not rows:
        raise BusinessError("该汇总单下没有本门店的分拣明细，无法装车")
    merged: dict[tuple[int, str], dict[str, Any]] = {}
    for row in rows:
        key = (row.sku_id, row.batch_no)
        if key in merged:
            merged[key]["qty_base"] = merged[key]["qty_base"] + row.qty_base
            continue
        merged[key] = {
            "pick_item_id": row.id,
            "sku_id": row.sku_id,
            "batch_no": row.batch_no,
            "qty_base": row.qty_base,
        }
    return list(merged.values())


def _assert_pick_item(
    db: Session, payload: DeliveryCreate, pick_item_id: int, sku_id: int, batch_no: str
) -> None:
    """显式指定来源分拣明细时校验单据链：同汇总单、同门店、同 SKU、同批次。"""
    row = db.execute(
        select(PickItem.sku_id, PickItem.batch_no, Pick.summary_id, Pick.store_id)
        .join(Pick, Pick.id == PickItem.pick_id)
        .where(PickItem.id == pick_item_id, _not_deleted(Pick))
    ).first()
    if row is None:
        raise NotFoundError("来源分拣明细不存在")
    if row[0] != sku_id or row[1] != batch_no:
        raise BusinessError(f"分拣明细 {pick_item_id} 与明细行的 SKU/批次不一致")
    if row[2] != payload.summary_id or row[3] != payload.store_id:
        raise BusinessError(f"分拣明细 {pick_item_id} 不属于该汇总单/门店")


# --------------------------------------------------------------------------- 状态机
def assert_transition(delivery: Delivery, target: str) -> None:
    """状态机判定：非法流转（含终态再签收、未发车即签收）→ 40900。"""
    if target not in DELIVERY_TRANSITIONS.get(delivery.status, ()):
        raise ConflictError(f"配送单状态 {delivery.status} 不能流转到 {target}")


def _transition(delivery: Delivery, target: str) -> None:
    assert_transition(delivery, target)
    delivery.status = target


# --------------------------------------------------------------------------- 签收辅助
def derive_sign_status(pairs: Sequence[tuple[DeliveryItem, Decimal]]) -> str:
    """由明细差异推导签收状态：全部实收=full、全部为 0=reject、其余=partial。"""
    if all(sign_qty == item.qty_base for item, sign_qty in pairs):
        return "full"
    if all(sign_qty == 0 for _, sign_qty in pairs):
        return "reject"
    return "partial"


def _match_sign_items(
    delivery_items: Sequence[DeliveryItem], payload: SignIn
) -> tuple[list[tuple[DeliveryItem, Decimal]], str]:
    """签收明细与配送明细按 (sku_id, batch_no) 对齐：缺行/多行 40000。"""
    if not delivery_items:
        raise BusinessError("配送单没有明细，无法签收")
    expected = {(item.sku_id, item.batch_no): item for item in delivery_items}
    provided = {(item.sku_id, item.batch_no): item.sign_qty_base for item in payload.items}
    missing = sorted(set(expected) - set(provided))
    unknown = sorted(set(provided) - set(expected))
    if missing or unknown:
        detail = []
        if missing:
            detail.append("缺行：" + ", ".join(f"{sku}/{batch}" for sku, batch in missing))
        if unknown:
            detail.append("多行：" + ", ".join(f"{sku}/{batch}" for sku, batch in unknown))
        raise BusinessError("签收明细与配送明细不一致（" + "；".join(detail) + "）")
    pairs = [(expected[key], provided[key]) for key in sorted(expected)]
    return pairs, derive_sign_status(pairs)


def resolve_sign_status(explicit: str | None, derived: str) -> str:
    """显式状态必须与明细推导一致，否则 40000（避免「实收全满却标记拒收」这类脏数据）。"""
    if explicit is None or explicit == derived:
        return derived
    raise BusinessError(f"签收状态 {explicit} 与明细差异推导结果 {derived} 不一致")


def _sign_request_fingerprint(
    payload: SignIn, status: str, pairs: Sequence[tuple[DeliveryItem, Decimal]]
) -> str:
    return fingerprint_payload(
        {
            "status": status,
            "remark": payload.remark,
            "items": [
                {
                    "sku_id": item.sku_id,
                    "batch_no": item.batch_no,
                    "sign_qty_base": _decimal_token(sign_qty),
                }
                for item, sign_qty in pairs
            ],
        }
    )


def _sign_stored_fingerprint(db: Session, sign: Sign) -> str:
    rows = db.execute(
        select(SignItem.sku_id, SignItem.batch_no, SignItem.sign_qty_base).where(
            SignItem.sign_id == sign.id
        )
    ).all()
    items = sorted(
        (
            {
                "sku_id": row[0],
                "batch_no": row[1],
                "sign_qty_base": _decimal_token(row[2]),
            }
            for row in rows
        ),
        key=lambda row: (row["sku_id"], row["batch_no"]),
    )
    return fingerprint_payload({"status": sign.status, "remark": sign.remark, "items": items})


def list_sign_items(db: Session, sign_id: int) -> list[SignItem]:
    """按签收单头取明细（差异生成列随行返回）。"""
    stmt = select(SignItem).where(SignItem.sign_id == sign_id).order_by(SignItem.id.asc())
    return list(db.scalars(stmt).all())


# --------------------------------------------------------------------------- 库存落定
def _resolve_batch_meta(
    db: Session, *, sku_id: int, batch_no: str, moment: datetime
) -> tuple[datetime, date | None]:
    """取批次效期：① 总部仓同批次结存 → ② batch_flow 效期快照 → ③ SKU 保质期推算。"""
    row = db.execute(
        select(BatchStock.expire_at, BatchStock.produced_at)
        .where(
            BatchStock.store_id == HQ_STORE_ID,
            BatchStock.sku_id == sku_id,
            BatchStock.batch_no == batch_no,
        )
        .order_by(BatchStock.id.desc())
        .limit(1)
    ).first()
    if row is not None and row[0] is not None:
        return row[0], row[1]
    snapshot = db.scalar(
        select(BatchFlow.expire_at)
        .where(
            BatchFlow.sku_id == sku_id,
            BatchFlow.batch_no == batch_no,
            BatchFlow.expire_at.is_not(None),
        )
        .order_by(BatchFlow.id.desc())
        .limit(1)
    )
    if snapshot is not None:
        return snapshot, None
    sku = db.scalar(select(Sku).where(Sku.id == sku_id))  # 含软删：历史批次仍需效期
    if sku is not None:
        return moment + timedelta(hours=int(sku.shelf_life_hours or 0)), None
    raise BusinessError(f"批次 {batch_no} 效期未知，无法将签收量落定为门店库存")


def _credit_store_stock(
    db: Session,
    delivery: Delivery,
    pairs: Sequence[tuple[DeliveryItem, Decimal]],
    *,
    operator_id: int,
    occurred_at: datetime,
) -> None:
    """签收落定门店库存：batch_stock 加量 + batch_flow(receive_add) 同一事务写入。"""
    for item, sign_qty in pairs:
        if sign_qty <= 0:
            continue
        stock = db.scalar(
            select(BatchStock)
            .where(
                _not_deleted(BatchStock),
                BatchStock.store_id == delivery.store_id,
                BatchStock.sku_id == item.sku_id,
                BatchStock.batch_no == item.batch_no,
            )
            .with_for_update()
        )
        if stock is None:
            expire_at, produced_at = _resolve_batch_meta(
                db, sku_id=item.sku_id, batch_no=item.batch_no, moment=occurred_at
            )
            stock = BatchStock(
                store_id=delivery.store_id,
                sku_id=item.sku_id,
                batch_no=item.batch_no,
                qty_base=Decimal("0.000"),
                produced_at=produced_at,
                expire_at=expire_at,
                version=0,
                created_by=operator_id,
                updated_by=operator_id,
            )
            db.add(stock)
            db.flush()
        stock.qty_base = stock.qty_base + sign_qty
        stock.version = int(stock.version or 0) + 1
        stock.updated_by = operator_id
        db.add(
            BatchFlow(
                store_id=delivery.store_id,
                sku_id=item.sku_id,
                batch_no=item.batch_no,
                flow_type="receive_add",
                qty_change_base=sign_qty,
                qty_after_base=stock.qty_base,
                expire_at=stock.expire_at,
                doc_type="other",
                doc_id=delivery.id,
                doc_no=delivery.delivery_no,
                doc_item_id=item.id,
                operate_by=operator_id,
                occurred_at=occurred_at,
                remark="配送签收入库",
            )
        )


# --------------------------------------------------------------------------- 装车
def create_delivery(
    db: Session,
    payload: DeliveryCreate,
    *,
    actor: Actor | None = None,
    operator_id: int | None = None,
    idempotency_key: str | None = None,
    now: datetime | None = None,
) -> Delivery:
    """POST /deliveries（装车）：落配送单 + 明细，状态 loaded，loaded_at=当前时间。

    幂等：Idempotency-Key 命中且请求体一致 → 返回首次结果；异体 → 40900。
    """
    moment = now or datetime.now()
    operator = operator_id if operator_id is not None else (actor.user_id if actor else None)
    item_values = _resolve_items(db, payload)
    request_values = _delivery_request_values(payload, item_values)
    request_fp = fingerprint_payload(request_values)

    existing = _find_by_idempotency_key(db, idempotency_key)
    if existing is not None:
        if fingerprint_payload(_delivery_stored_values(db, existing)) != request_fp:
            raise ConflictError("幂等键重复且请求内容与首次装车不一致")
        return existing

    store = db.scalar(select(Store).where(_not_deleted(Store), Store.id == payload.store_id))
    if store is None:
        raise NotFoundError("门店不存在")

    for attempt in range(MAX_DOC_NO_ATTEMPTS):
        delivery = Delivery(
            delivery_no=_next_doc_no(
                db, Delivery.delivery_no, prefix=DELIVERY_NO_PREFIX, moment=moment
            ),
            summary_id=payload.summary_id,
            store_id=payload.store_id,
            require_date=payload.require_date,
            driver_id=payload.driver_id,
            plate_no=payload.plate_no,
            status="loaded",
            loaded_at=moment,
            idempotency_key=idempotency_key,
            created_by=operator,
            updated_by=operator,
        )
        try:
            with db.begin_nested():
                db.add(delivery)
                db.flush()
                for row in item_values:
                    db.add(
                        DeliveryItem(
                            delivery_id=delivery.id,
                            created_by=operator,
                            updated_by=operator,
                            **row,
                        )
                    )
                db.flush()
        except IntegrityError as exc:
            # 并发下同键请求已插入：回查后按幂等语义返回
            found = _find_by_idempotency_key(db, idempotency_key)
            if found is not None:
                if fingerprint_payload(_delivery_stored_values(db, found)) != request_fp:
                    raise ConflictError("幂等键重复且请求内容与首次装车不一致") from exc
                return found
            if attempt == MAX_DOC_NO_ATTEMPTS - 1:
                raise ConflictError("配送单号生成冲突，请重试") from exc
            continue
        return delivery
    raise ConflictError("配送单号生成冲突，请重试")  # pragma: no cover（循环内必返回或抛错）


# --------------------------------------------------------------------------- 发车 / 查询
def depart(
    db: Session,
    delivery_id: int,
    *,
    actor: Actor | None = None,
    operator_id: int | None = None,
) -> Delivery:
    """POST /deliveries/{id}/depart（发车）：loaded → on_way，非法流转 40900。"""
    delivery = _load_delivery(db, delivery_id)
    assert_can_depart(delivery, actor)
    _transition(delivery, "on_way")
    delivery.updated_by = (
        operator_id if operator_id is not None else (actor.user_id if actor else None)
    )
    db.flush()
    return delivery


def list_deliveries(
    db: Session,
    *,
    actor: Actor | None = None,
    driver_id: int | None = None,
    require_date: date | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult[Delivery]:
    """GET /deliveries?driver_id=&require_date=：司机当日任务 / 总部按日按状态查询。

    门店账号强制注入本店条件；纯司机强制注入 driver_id=本人（显式请求他人 → 40300）。
    """
    conditions: list[Any] = [_not_deleted(Delivery)]
    if actor is not None and actor.store_id is not None:
        conditions.append(Delivery.store_id == actor.store_id)
    if actor is not None and actor.is_driver_scoped:
        if driver_id is not None and driver_id != actor.user_id:
            raise PermissionDeniedError("司机只能查看自己的配送任务")
        conditions.append(Delivery.driver_id == actor.user_id)
    elif driver_id is not None:
        conditions.append(Delivery.driver_id == driver_id)
    if require_date is not None:
        conditions.append(Delivery.require_date == require_date)
    if status is not None:
        conditions.append(Delivery.status == status)
    return _page_query(
        db,
        Delivery,
        conditions,
        page=page,
        page_size=page_size,
        order_by=(Delivery.require_date.desc(), Delivery.id.desc()),
    )


def get_delivery(db: Session, delivery_id: int, *, actor: Actor | None = None) -> Delivery:
    """GET /deliveries/{id}：详情（越数据范围 40300）。"""
    delivery = _load_delivery(db, delivery_id)
    assert_can_view(delivery, actor)
    return delivery


def list_delivery_items(db: Session, delivery_id: int) -> list[DeliveryItem]:
    """按配送单头取全部明细（详情接口随头返回）。"""
    return _load_items(db, delivery_id)


# --------------------------------------------------------------------------- 签收
def sign(
    db: Session,
    delivery_id: int,
    payload: SignIn,
    *,
    actor: Actor | None = None,
    operator_id: int | None = None,
    idempotency_key: str | None = None,
    now: datetime | None = None,
) -> Sign:
    """POST /deliveries/{id}/sign（签收，幂等）：写 sign + sign_item，流转配送单状态。

    - 仅 on_way 可签收（loaded 未发车 → 40900），终态单重复签收按重放处理；
    - 实收数量写 sign_item，差异由数据库生成列 diff_qty_base 计算（正=少送、负=多收）；
    - 签收状态 full/partial/reject 与明细推导一致，并映射配送单 signed/partial/rejected；
    - 相同请求重放（同一配送单或同一 Idempotency-Key）返回首次结果，异体 40900。
    """
    moment = now or datetime.now()
    signer = operator_id if operator_id is not None else (actor.user_id if actor else None)
    if signer is None:
        raise BusinessError("签收需要操作人身份")

    delivery = _load_delivery(db, delivery_id)
    assert_can_sign(delivery, actor)

    delivery_items = _load_items(db, delivery.id)
    pairs, derived = _match_sign_items(delivery_items, payload)
    sign_status = resolve_sign_status(payload.status, derived)
    request_fp = _sign_request_fingerprint(payload, sign_status, pairs)

    existing = _find_sign_by_delivery(db, delivery.id)
    if existing is None:
        existing = _find_sign_by_key(db, idempotency_key)
        if existing is not None and existing.delivery_id != delivery.id:
            raise ConflictError("该幂等键已被其他配送单的签收单占用")
    if existing is not None:
        if _sign_stored_fingerprint(db, existing) != request_fp:
            raise ConflictError("该配送单已签收且本次明细与首次签收不一致，请走冲正流程")
        return existing

    target = SIGN_TO_DELIVERY_STATUS[sign_status]
    assert_transition(delivery, target)

    sign_at = payload.sign_at or moment
    sign_row = Sign(
        delivery_id=delivery.id,
        store_id=delivery.store_id,
        sign_by=signer,
        sign_at=sign_at,
        status=sign_status,
        remark=payload.remark,
        idempotency_key=idempotency_key,
        created_by=signer,
        updated_by=signer,
    )
    try:
        with db.begin_nested():
            db.add(sign_row)
            db.flush()
            for item, sign_qty in pairs:
                db.add(
                    SignItem(
                        sign_id=sign_row.id,
                        sku_id=item.sku_id,
                        batch_no=item.batch_no,
                        send_qty_base=item.qty_base,
                        sign_qty_base=sign_qty,
                        created_by=signer,
                        updated_by=signer,
                    )
                )
            db.flush()
    except IntegrityError as exc:
        # uk_delivery / uk_idem 并发兜底：回查后按重放语义返回
        found = _find_sign_by_delivery(db, delivery.id) or _find_sign_by_key(db, idempotency_key)
        if found is None:
            raise
        if found.delivery_id != delivery.id:
            raise ConflictError("该幂等键已被其他配送单的签收单占用") from exc
        if _sign_stored_fingerprint(db, found) != request_fp:
            raise ConflictError("该配送单已签收且本次明细与首次签收不一致，请走冲正流程") from exc
        return found

    _transition(delivery, target)
    delivery.signed_at = sign_at
    delivery.updated_by = signer
    if SIGN_CREDIT_STORE_STOCK:
        _credit_store_stock(db, delivery, pairs, operator_id=signer, occurred_at=moment)
    db.flush()
    return sign_row


def get_sign(db: Session, sign_id: int, *, actor: Actor | None = None) -> SignDetail:
    """GET /signs/{id}：签收单详情（含明细与关联配送单号）；越数据范围 40300。"""
    sign = db.scalar(select(Sign).where(Sign.id == sign_id))
    if sign is None:
        raise NotFoundError("签收单不存在")
    delivery = db.scalar(
        select(Delivery).where(_not_deleted(Delivery), Delivery.id == sign.delivery_id)
    )
    if actor is not None:
        if actor.store_id is not None and sign.store_id != actor.store_id:
            raise PermissionDeniedError("只能查看本店的签收单")
        if actor.is_driver_scoped and (delivery is None or delivery.driver_id != actor.user_id):
            raise PermissionDeniedError("司机只能查看自己配送任务的签收单")
    if delivery is None:
        raise NotFoundError("签收单对应的配送单不存在")
    return SignDetail(sign=sign, items=list_sign_items(db, sign.id), delivery=delivery)
