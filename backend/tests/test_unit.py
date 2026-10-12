"""单元测试：纯函数（不依赖数据库与网络）。"""

from __future__ import annotations

from decimal import Decimal

from app.core.security import hash_password, verify_password
from app.utils.unit import grams_to_jin, jin_to_kg, kg_to_jin, money


def test_jin_kg_round_trip() -> None:
    """斤与公斤的双向换算必须自洽。"""
    assert jin_to_kg(10) == Decimal("5.000")
    assert kg_to_jin(5) == Decimal("10.000")


def test_grams_and_money() -> None:
    """克与斤、金额小数位约定。"""
    assert grams_to_jin(500) == Decimal("1.000")
    assert money(Decimal("12.345")) == Decimal("12.35")


def test_password_hash_and_verify() -> None:
    """口令只存哈希且可校验；错误口令必须不通过。"""
    hashed = hash_password("Njxj@2026")
    assert hashed != "Njxj@2026"
    assert verify_password("Njxj@2026", hashed)
    assert not verify_password("wrong-password", hashed)
