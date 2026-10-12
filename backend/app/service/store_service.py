"""主数据服务：门店 / SKU / 供应商 / 价目（§7.1 模型 + §8.2 端点）。

分层铁律：service 是唯一事务边界与业务判定处；本层不感知 HTTP（只抛 BusinessError）。

幂等：§7.1 的主数据表没有 idempotency_key 列，幂等锚点取业务唯一索引——
uk_store_no / uk_sku_no / uk_supplier_no / uk_sku_type_from；同一业务键重复提交返回
首次结果，业务键相同但请求体不一致返回 40900。若实体带 idempotency_key 列则优先用它。

乐观锁：优先实体 version 列；主数据表无 version 列，版本令牌回退为 updated_at 的
Unix 毫秒，更新请求回传该令牌，不一致返回 40900。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.model.base import SOFT_DELETE_SENTINEL
from app.model.store import Price, Sku, Store, Supplier
from app.schema.store import (
    PriceCreate,
    SkuCreate,
    SkuUpdate,
    StoreCreate,
    StoreUpdate,
    SupplierCreate,
    SupplierUpdate,
)

# 指纹字段：与 Create 契约字段一致，用于判定“同键重复提交”是否同一请求体
STORE_FINGERPRINT_FIELDS = (
    "store_no",
    "name",
    "region",
    "address",
    "contact_name",
    "contact_phone",
    "delivery_cycle",
    "status",
)
SKU_FINGERPRINT_FIELDS = (
    "sku_no",
    "name",
    "category",
    "spec",
    "unit",
    "base_unit",
    "convert_factor",
    "shelf_life_hours",
    "supply_type",
    "status",
)
SUPPLIER_FINGERPRINT_FIELDS = (
    "supplier_no",
    "name",
    "contact_name",
    "contact_phone",
    "payment_terms",
    "status",
)
PRICE_FINGERPRINT_FIELDS = (
    "sku_id",
    "price_type",
    "price",
    "effective_from",
    "effective_to",
)


# --------------------------------------------------------------------------- 纯逻辑
def _canonical(value: Any) -> Any:
    """指纹归一化：Decimal 去尾零、时间转 ISO 串，避免等价值被误判为不同请求。"""
    if isinstance(value, Decimal):
        return str(value.normalize())
    if isinstance(value, date):
        return value.isoformat()
    return value


def fingerprint_payload(values: Mapping[str, Any]) -> str:
    """请求指纹：字段排序 + 归一化后的 sha256，与字段书写顺序无关。"""
    normalized = {key: _canonical(value) for key, value in values.items()}
    dumped = json.dumps(
        normalized, sort_keys=True, default=str, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def fingerprint_entity(entity: Any, fields: Sequence[str]) -> str:
    """实体指纹：按同一套字段与规则计算，可与其创建请求的指纹直接比较。"""
    return fingerprint_payload({name: getattr(entity, name, None) for name in fields})


def resolve_idempotent_create[T](
    *,
    find_existing: Callable[[], T | None],
    create: Callable[[], T],
    request_fingerprint: str,
    existing_fingerprint: Callable[[T], str],
    conflict_message: str = "幂等键重复且请求体与首次提交不一致",
) -> tuple[T, bool]:
    """幂等解析（纯逻辑）。

    命中且请求体一致 → 返回首次结果；命中但请求体不一致 → 40900；未命中 → 新建。
    """
    existing = find_existing()
    if existing is not None:
        if existing_fingerprint(existing) != request_fingerprint:
            raise ConflictError(conflict_message)
        return existing, False
    return create(), True


def apply_soft_delete(entity: Any, *, now: datetime | None = None) -> datetime:
    """软删除（§7 通用约定）：deleted_at 置为当前时间，绝不物理删除。"""
    moment = now or datetime.now()
    entity.deleted_at = moment
    return moment


@dataclass(frozen=True)
class PageResult[T]:
    """分页结果：DB 路径与内存分页共用同一形状。"""

    items: list[T]
    total: int


def paginate[T](items: Sequence[T], *, page: int, page_size: int) -> PageResult[T]:
    """内存分页（纯逻辑，便于单测）。"""
    total = len(items)
    start = (page - 1) * page_size
    return PageResult(items=list(items[start:start + page_size]), total=total)


def current_version_token(entity: Any) -> int | None:
    """版本令牌：优先实体 version 列，否则取 updated_at 的 Unix 毫秒。"""
    raw_version = getattr(entity, "version", None)
    if raw_version is not None:
        return int(raw_version)
    updated_at = getattr(entity, "updated_at", None)
    if isinstance(updated_at, datetime):
        return int(updated_at.timestamp() * 1000)
    return None


def check_optimistic_lock(entity: Any, version: int | None, *, resource: str = "该记录") -> None:
    """乐观锁校验：version 非空且与当前令牌不一致 → 40900。"""
    if version is None:
        return
    current = current_version_token(entity)
    if current is None:
        return
    if int(version) != current:
        raise ConflictError(f"{resource}已被他人修改，请刷新后重试")


# --------------------------------------------------------------------------- DB 内部
def _not_deleted(model: type[Any]) -> Any:
    return model.deleted_at == SOFT_DELETE_SENTINEL


def _find_one(db: Session, model: type[Any], *conditions: Any) -> Any:
    return db.scalar(select(model).where(_not_deleted(model), *conditions))


def _load_or_404(db: Session, model: type[Any], entity_id: int, label: str) -> Any:
    entity = _find_one(db, model, model.id == entity_id)
    if entity is None:
        raise NotFoundError(f"{label}不存在")
    return entity


def _page_query(
    db: Session,
    model: type[Any],
    conditions: Sequence[Any],
    *,
    page: int,
    page_size: int,
    order_by: Sequence[Any],
) -> PageResult[Any]:
    total = int(db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0)
    stmt = (
        select(model)
        .where(*conditions)
        .order_by(*order_by)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return PageResult(items=list(db.scalars(stmt).all()), total=total)


def _idempotent_lookup(
    db: Session,
    model: type[Any],
    *,
    natural_conditions: Sequence[Any],
    idempotency_key: str | None,
) -> Any:
    """幂等查找：实体有 idempotency_key 列时优先按键查，否则退回业务唯一键。"""
    if idempotency_key and hasattr(model, "idempotency_key"):
        return _find_one(db, model, model.idempotency_key == idempotency_key)
    return _find_one(db, model, *natural_conditions)


def _insert_idempotent[T](
    db: Session,
    *,
    build: Callable[[], T],
    find_existing: Callable[[], T | None],
    request_fingerprint: str,
    existing_fingerprint: Callable[[T], str],
    conflict_message: str,
) -> T:
    """幂等新建：先查后插；并发下由唯一索引兜底，撞键后回查并比对请求体。"""

    def _create() -> T:
        entity = build()
        db.add(entity)
        db.flush()
        return entity

    try:
        # savepoint：唯一索引冲突只回滚本次插入，会话仍可用于回查
        with db.begin_nested():
            entity, _created = resolve_idempotent_create(
                find_existing=find_existing,
                create=_create,
                request_fingerprint=request_fingerprint,
                existing_fingerprint=existing_fingerprint,
                conflict_message=conflict_message,
            )
    except IntegrityError as exc:
        found = find_existing()
        if found is None or existing_fingerprint(found) != request_fingerprint:
            raise ConflictError(conflict_message) from exc
        return found
    return entity


# --------------------------------------------------------------------------- 门店
def list_stores(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    status: int | None = None,
    store_id: int | None = None,
) -> PageResult[Store]:
    """门店分页列表；store_id 非空时强制本店条件（数据范围，§8.1）。"""
    conditions = [_not_deleted(Store)]
    if store_id is not None:
        conditions.append(Store.id == store_id)
    if status is not None:
        conditions.append(Store.status == status)
    if keyword:
        like = f"%{keyword}%"
        conditions.append(or_(Store.store_no.like(like), Store.name.like(like)))
    return _page_query(
        db, Store, conditions, page=page, page_size=page_size, order_by=(Store.id.desc(),)
    )


def get_store(db: Session, store_id: int) -> Store:
    """按 id 查门店；不存在或已软删 → 40400。"""
    return _load_or_404(db, Store, store_id, "门店")


def create_store(
    db: Session,
    payload: StoreCreate,
    *,
    operator_id: int | None = None,
    idempotency_key: str | None = None,
) -> Store:
    """新建门店（幂等）：store_no 为业务唯一键，重复提交返回首次结果。"""
    values = payload.model_dump()
    return _insert_idempotent(
        db,
        build=lambda: Store(**values, created_by=operator_id, updated_by=operator_id),
        find_existing=lambda: _idempotent_lookup(
            db,
            Store,
            natural_conditions=(Store.store_no == payload.store_no,),
            idempotency_key=idempotency_key,
        ),
        request_fingerprint=fingerprint_payload(values),
        existing_fingerprint=lambda entity: fingerprint_entity(entity, STORE_FINGERPRINT_FIELDS),
        conflict_message="门店编码已存在且内容与首次提交不一致",
    )


def update_store(
    db: Session, store_id: int, payload: StoreUpdate, *, operator_id: int | None = None
) -> Store:
    """修改门店（乐观锁）：version 令牌不一致 → 40900。"""
    store = get_store(db, store_id)
    check_optimistic_lock(store, payload.version, resource="门店")
    for field, value in payload.model_dump(exclude_unset=True, exclude={"version"}).items():
        setattr(store, field, value)
    store.updated_by = operator_id
    db.flush()
    return store


def delete_store(db: Session, store_id: int, *, operator_id: int | None = None) -> Store:
    """软删除门店：仅置 deleted_at，历史单据仍可关联。"""
    store = get_store(db, store_id)
    apply_soft_delete(store)
    store.updated_by = operator_id
    db.flush()
    return store


# --------------------------------------------------------------------------- SKU
def list_skus(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    category: str | None = None,
    keyword: str | None = None,
    status: int | None = None,
) -> PageResult[Sku]:
    """SKU 分页列表/筛选（品类、关键字、状态）。"""
    conditions = [_not_deleted(Sku)]
    if category:
        conditions.append(Sku.category == category)
    if status is not None:
        conditions.append(Sku.status == status)
    if keyword:
        like = f"%{keyword}%"
        conditions.append(or_(Sku.sku_no.like(like), Sku.name.like(like)))
    return _page_query(
        db, Sku, conditions, page=page, page_size=page_size, order_by=(Sku.id.desc(),)
    )


def get_sku(db: Session, sku_id: int) -> Sku:
    """按 id 查 SKU；不存在或已软删 → 40400。"""
    return _load_or_404(db, Sku, sku_id, "SKU")


def create_sku(
    db: Session,
    payload: SkuCreate,
    *,
    operator_id: int | None = None,
    idempotency_key: str | None = None,
) -> Sku:
    """新建 SKU（幂等）：sku_no 为业务唯一键。"""
    values = payload.model_dump()
    return _insert_idempotent(
        db,
        build=lambda: Sku(**values, created_by=operator_id, updated_by=operator_id),
        find_existing=lambda: _idempotent_lookup(
            db,
            Sku,
            natural_conditions=(Sku.sku_no == payload.sku_no,),
            idempotency_key=idempotency_key,
        ),
        request_fingerprint=fingerprint_payload(values),
        existing_fingerprint=lambda entity: fingerprint_entity(entity, SKU_FINGERPRINT_FIELDS),
        conflict_message="SKU 编码已存在且内容与首次提交不一致",
    )


def update_sku(
    db: Session, sku_id: int, payload: SkuUpdate, *, operator_id: int | None = None
) -> Sku:
    """修改 SKU（乐观锁）。"""
    sku = get_sku(db, sku_id)
    check_optimistic_lock(sku, payload.version, resource="SKU")
    for field, value in payload.model_dump(exclude_unset=True, exclude={"version"}).items():
        setattr(sku, field, value)
    sku.updated_by = operator_id
    db.flush()
    return sku


def delete_sku(db: Session, sku_id: int, *, operator_id: int | None = None) -> Sku:
    """软删除 SKU。"""
    sku = get_sku(db, sku_id)
    apply_soft_delete(sku)
    sku.updated_by = operator_id
    db.flush()
    return sku


# --------------------------------------------------------------------------- 供应商
def list_suppliers(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    status: int | None = None,
) -> PageResult[Supplier]:
    """供应商分页列表。"""
    conditions = [_not_deleted(Supplier)]
    if status is not None:
        conditions.append(Supplier.status == status)
    if keyword:
        like = f"%{keyword}%"
        conditions.append(or_(Supplier.supplier_no.like(like), Supplier.name.like(like)))
    return _page_query(
        db,
        Supplier,
        conditions,
        page=page,
        page_size=page_size,
        order_by=(Supplier.id.desc(),),
    )


def get_supplier(db: Session, supplier_id: int) -> Supplier:
    """按 id 查供应商；不存在或已软删 → 40400。"""
    return _load_or_404(db, Supplier, supplier_id, "供应商")


def create_supplier(
    db: Session,
    payload: SupplierCreate,
    *,
    operator_id: int | None = None,
    idempotency_key: str | None = None,
) -> Supplier:
    """新建供应商（幂等）：supplier_no 为业务唯一键。"""
    values = payload.model_dump()
    return _insert_idempotent(
        db,
        build=lambda: Supplier(**values, created_by=operator_id, updated_by=operator_id),
        find_existing=lambda: _idempotent_lookup(
            db,
            Supplier,
            natural_conditions=(Supplier.supplier_no == payload.supplier_no,),
            idempotency_key=idempotency_key,
        ),
        request_fingerprint=fingerprint_payload(values),
        existing_fingerprint=lambda entity: fingerprint_entity(
            entity, SUPPLIER_FINGERPRINT_FIELDS
        ),
        conflict_message="供应商编码已存在且内容与首次提交不一致",
    )


def update_supplier(
    db: Session,
    supplier_id: int,
    payload: SupplierUpdate,
    *,
    operator_id: int | None = None,
) -> Supplier:
    """修改供应商（乐观锁）。"""
    supplier = get_supplier(db, supplier_id)
    check_optimistic_lock(supplier, payload.version, resource="供应商")
    for field, value in payload.model_dump(exclude_unset=True, exclude={"version"}).items():
        setattr(supplier, field, value)
    supplier.updated_by = operator_id
    db.flush()
    return supplier


def delete_supplier(db: Session, supplier_id: int, *, operator_id: int | None = None) -> Supplier:
    """软删除供应商。"""
    supplier = get_supplier(db, supplier_id)
    apply_soft_delete(supplier)
    supplier.updated_by = operator_id
    db.flush()
    return supplier


# --------------------------------------------------------------------------- 价目
def list_prices(
    db: Session,
    *,
    sku_id: int,
    on_date: date | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult[Price]:
    """查历史当时价：date 命中生效区间 [effective_from, effective_to]（NULL=现行有效）。"""
    conditions = [_not_deleted(Price), Price.sku_id == sku_id]
    if on_date is not None:
        conditions.append(Price.effective_from <= on_date)
        conditions.append(or_(Price.effective_to.is_(None), Price.effective_to >= on_date))
    return _page_query(
        db,
        Price,
        conditions,
        page=page,
        page_size=page_size,
        order_by=(Price.effective_from.desc(), Price.id.desc()),
    )


def get_price(db: Session, price_id: int) -> Price:
    """按 id 查价目；不存在或已软删 → 40400。"""
    return _load_or_404(db, Price, price_id, "价目")


def create_price(
    db: Session,
    payload: PriceCreate,
    *,
    operator_id: int | None = None,
    idempotency_key: str | None = None,
) -> Price:
    """新增价目（幂等）：uk_sku_type_from 为业务唯一键；逻辑外键先校验 SKU 存在。"""
    get_sku(db, payload.sku_id)
    values = payload.model_dump()
    return _insert_idempotent(
        db,
        build=lambda: Price(**values, created_by=operator_id, updated_by=operator_id),
        find_existing=lambda: _idempotent_lookup(
            db,
            Price,
            natural_conditions=(
                Price.sku_id == payload.sku_id,
                Price.price_type == payload.price_type,
                Price.effective_from == payload.effective_from,
            ),
            idempotency_key=idempotency_key,
        ),
        request_fingerprint=fingerprint_payload(values),
        existing_fingerprint=lambda entity: fingerprint_entity(entity, PRICE_FINGERPRINT_FIELDS),
        conflict_message="该 SKU 同类型同生效日的价目已存在且内容不一致",
    )


def delete_price(db: Session, price_id: int, *, operator_id: int | None = None) -> Price:
    """软删除价目。"""
    price = get_price(db, price_id)
    apply_soft_delete(price)
    price.updated_by = operator_id
    db.flush()
    return price
