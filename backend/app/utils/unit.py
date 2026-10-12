"""单位换算纯函数。

业务背景：门店按「斤」下单与验收，仓储分拣与配送按「公斤」称重，对账按「斤」计价；
换算系数只此一处，禁止各层各写一份。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# 1 公斤 = 2 斤（市斤）
KG_PER_JIN = Decimal("0.5")


def jin_to_kg(jin: Decimal | float | int) -> Decimal:
    """斤 → 公斤（保留 3 位小数）。"""
    return (Decimal(str(jin)) * KG_PER_JIN).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def kg_to_jin(kg: Decimal | float | int) -> Decimal:
    """公斤 → 斤（保留 3 位小数）。"""
    return (Decimal(str(kg)) / KG_PER_JIN).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def jin_to_grams(jin: Decimal | float | int) -> int:
    """斤 → 克（整数）。"""
    return int((Decimal(str(jin)) * Decimal("500")).to_integral_value(rounding=ROUND_HALF_UP))


def grams_to_jin(grams: Decimal | float | int) -> Decimal:
    """克 → 斤（保留 3 位小数）。"""
    return (Decimal(str(grams)) / Decimal("500")).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def money(value: Decimal | float | int) -> Decimal:
    """金额统一保留 2 位小数，避免浮点误差进对账单。"""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
