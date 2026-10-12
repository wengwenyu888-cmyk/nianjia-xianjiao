"""service 层纯逻辑测试：幂等、软删除、分页、乐观锁、指纹。

本地跑法（backend 目录下）：
    uv run pytest tests/test_store_service.py -q

不连数据库：只测纯函数与内存对象，避开 SQLite 与 MySQL 方言类型差异。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.exceptions import ConflictError
from app.model.base import SOFT_DELETE_SENTINEL
from app.schema.store import PriceCreate, SkuCreate, StoreCreate
from app.service import store_service as svc


# --------------------------------------------------------------------------- 指纹
def test_fingerprint_is_order_independent() -> None:
    assert svc.fingerprint_payload({"a": 1, "b": 2}) == svc.fingerprint_payload({"b": 2, "a": 1})


def test_fingerprint_normalizes_decimal_and_date() -> None:
    left = svc.fingerprint_payload(
        {"convert_factor": Decimal("1"), "effective_from": date(2026, 1, 1)}
    )
    right = svc.fingerprint_payload(
        {"convert_factor": Decimal("1.0000"), "effective_from": date(2026, 1, 1)}
    )
    assert left == right


def test_entity_fingerprint_matches_payload_fingerprint() -> None:
    payload = StoreCreate(store_no="S001", name="门店")
    entity = SimpleNamespace(**payload.model_dump())
    assert svc.fingerprint_entity(entity, svc.STORE_FINGERPRINT_FIELDS) == svc.fingerprint_payload(
        payload.model_dump()
    )


def test_entity_fingerprint_normalizes_decimal_for_sku() -> None:
    payload = SkuCreate(
        sku_no="K1", name="馅料", category="面皮", unit="袋", base_unit="kg", shelf_life_hours=24
    )
    entity = SimpleNamespace(**{**payload.model_dump(), "convert_factor": Decimal("1.0000")})
    assert svc.fingerprint_entity(entity, svc.SKU_FINGERPRINT_FIELDS) == svc.fingerprint_payload(
        payload.model_dump()
    )


# --------------------------------------------------------------------------- 幂等
def test_resolve_idempotent_create_creates_when_absent() -> None:
    calls: list[str] = []

    def _create() -> str:
        calls.append("create")
        return "NEW"

    entity, created = svc.resolve_idempotent_create(
        find_existing=lambda: None,
        create=_create,
        request_fingerprint="fp",
        existing_fingerprint=lambda _: "fp",
    )
    assert entity == "NEW"
    assert created is True
    assert calls == ["create"]


def test_resolve_idempotent_create_returns_first_result_on_replay() -> None:
    entity, created = svc.resolve_idempotent_create(
        find_existing=lambda: "FIRST",
        create=lambda: "NEW",
        request_fingerprint="fp",
        existing_fingerprint=lambda _: "fp",
    )
    assert entity == "FIRST"
    assert created is False


def test_resolve_idempotent_create_conflicts_on_same_key_different_body() -> None:
    with pytest.raises(ConflictError) as excinfo:
        svc.resolve_idempotent_create(
            find_existing=lambda: "FIRST",
            create=lambda: "NEW",
            request_fingerprint="fp-2",
            existing_fingerprint=lambda _: "fp-1",
        )
    assert excinfo.value.code == 40900


# --------------------------------------------------------------------------- 软删除
def test_apply_soft_delete_marks_timestamp_not_physical_delete() -> None:
    entity = SimpleNamespace(deleted_at=SOFT_DELETE_SENTINEL)
    moment = datetime(2026, 10, 12, 12, 0, 0)
    returned = svc.apply_soft_delete(entity, now=moment)
    assert returned == moment
    assert entity.deleted_at == moment
    assert entity.deleted_at != SOFT_DELETE_SENTINEL


# --------------------------------------------------------------------------- 分页
def test_paginate_slices_and_counts() -> None:
    result = svc.paginate(list(range(25)), page=2, page_size=10)
    assert result.total == 25
    assert result.items == list(range(10, 20))


def test_paginate_beyond_last_page_returns_empty() -> None:
    result = svc.paginate([1, 2, 3], page=5, page_size=10)
    assert result.total == 3
    assert result.items == []


# --------------------------------------------------------------------------- 乐观锁
def test_current_version_token_prefers_version_column() -> None:
    entity = SimpleNamespace(version=3, updated_at=datetime(2026, 10, 12, 10, 0, 0))
    assert svc.current_version_token(entity) == 3


def test_current_version_token_falls_back_to_updated_at_ms() -> None:
    moment = datetime(2026, 10, 12, 10, 0, 0)
    entity = SimpleNamespace(updated_at=moment)
    assert svc.current_version_token(entity) == int(moment.timestamp() * 1000)


def test_check_optimistic_lock_passes_when_token_matches() -> None:
    moment = datetime(2026, 10, 12, 10, 0, 0)
    entity = SimpleNamespace(updated_at=moment)
    svc.check_optimistic_lock(entity, svc.current_version_token(entity))


def test_check_optimistic_lock_conflicts_on_stale_token() -> None:
    entity = SimpleNamespace(updated_at=datetime(2026, 10, 12, 10, 0, 0))
    with pytest.raises(ConflictError) as excinfo:
        svc.check_optimistic_lock(entity, 0)
    assert excinfo.value.code == 40900


def test_check_optimistic_lock_noop_without_token() -> None:
    svc.check_optimistic_lock(SimpleNamespace(updated_at=None), None)


# --------------------------------------------------------------------------- 契约校验
def test_price_create_rejects_inverted_effective_range() -> None:
    with pytest.raises(ValidationError):
        PriceCreate(
            sku_id=1,
            price_type="purchase",
            price=Decimal("3.5"),
            effective_from=date(2026, 1, 10),
            effective_to=date(2026, 1, 1),
        )


def test_store_create_defaults() -> None:
    payload = StoreCreate(store_no="S001", name="门店")
    assert payload.delivery_cycle == "daily"
    assert payload.status == 1
