"""补库存脚本（一次性/可重复）：给总部仓补齐全部 SKU 的批次库存 + 批次流水。

背景：种子里的示例要货单会与演示时新建的要货单一并进汇总，
若总部仓缺少对应 SKU 的批次库存，分拣会按 FIFO 正确报「库存不足」40900。
本脚本让演示数据自洽：每个 SKU 至少有一个未过期批次，库存量足以覆盖演示要货量。

幂等：已有未过期批次的 SKU 跳过，可重复执行。
用法（容器内）：python -m seed.seed_stock_topup
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.config import get_settings
from app.model.base import SOFT_DELETE_SENTINEL
from app.model.inventory import BatchFlow, BatchStock
from app.model.store import Sku

HQ_STORE_ID = 0
TOPUP_QTY = Decimal("500.000")
BATCH_PREFIX = "PC-TOPUP-"


def main() -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    settings = get_settings()
    engine = create_engine(settings.database_url, future=True)
    now = datetime.now()
    expire_at = (now + timedelta(days=30)).replace(microsecond=0)
    created, skipped = 0, 0

    with Session(engine) as db, db.begin():
        skus = db.scalars(select(Sku).where(Sku.deleted_at == SOFT_DELETE_SENTINEL)).all()
        for sku in skus:
            exists = db.scalar(
                select(BatchStock.id).where(
                    BatchStock.store_id == HQ_STORE_ID,
                    BatchStock.sku_id == sku.id,
                    BatchStock.qty_base > 0,
                    BatchStock.deleted_at == SOFT_DELETE_SENTINEL,
                ).limit(1)
            )
            if exists is not None:
                skipped += 1
                continue
            batch_no = f"{BATCH_PREFIX}{sku.sku_no}"
            stock = BatchStock(
                store_id=HQ_STORE_ID,
                sku_id=sku.id,
                batch_no=batch_no,
                qty_base=TOPUP_QTY,
                expire_at=expire_at,
                version=1,
                created_by=1,
            )
            db.add(stock)
            db.flush()
            db.add(
                BatchFlow(
                    store_id=HQ_STORE_ID,
                    sku_id=sku.id,
                    batch_no=batch_no,
                    flow_type="receive_add",
                    qty_change_base=TOPUP_QTY,
                    qty_after_base=TOPUP_QTY,
                    expire_at=expire_at,
                    doc_type="other",
                    doc_id=None,
                    doc_no=batch_no,
                    doc_item_id=None,
                    operate_by=1,
                    occurred_at=now,
                    remark="种子补库存：让演示要货-分拣链路自洽",
                )
            )
            created += 1

    print(f"补库存完成：新增 {created} 个 SKU 批次，跳过 {skipped} 个（已有库存）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
