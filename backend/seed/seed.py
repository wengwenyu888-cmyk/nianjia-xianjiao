#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""念家鲜饺供应链系统 · 种子数据初始化脚本（幂等）。

用法（在 backend/ 目录下执行）::

    uv run python -m seed.seed
    python seed/seed.py

设计要点：
- 幂等：每类数据先按业务唯一键查询，命中即跳过，可安全重复执行；
- 插入顺序：权限点 → 角色 → 门店 → 用户(+用户角色) → 角色权限映射
  → 供应商 → SKU → 价目表 → 批次库存 → 示例要货单。门店排在用户之前，
  是因为 store01 店长必须绑定「潍坊001店」的 store_id（真实依赖，非随意调整）；
- 软删字段 deleted_at 一律写哨兵值 SOFT_DELETE_SENTINEL（未删除）；
- 金额/数量一律用 Decimal，避免浮点误差；
- 日期按运行时当天动态推算，脚本内不写死“今天”。仅批次号前缀
  PC20261012 与价目表生效起始日 2026-10-01 按需求固定。

测试账号（明文口令仅用于开发/测试环境，生产环境禁止使用本脚本）::

    admin    / Admin@12345    总部管理员（store_id 为空 = 总部）
    ops      / Ops@12345      总部运营
    store01  / Store@12345    潍坊001 店长（绑定 WF001）
    driver01 / Driver@12345   司机

权限点严格取自 docs/02-架构与模块设计.md v0.3.1 §8.3（38 条）；角色权限映射
按同表「默认角色」列展开，其中 admin 按任务要求取全量 38 条。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

# 允许直接执行 seed/seed.py 时找到 app 包（把 backend/ 加入 sys.path）
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.model.base import SOFT_DELETE_SENTINEL  # noqa: E402
from app.model.inventory import BatchStock  # noqa: E402
from app.model.order import OrderHead, OrderItem  # noqa: E402
from app.model.store import Price, Sku, Store, Supplier  # noqa: E402
from app.model.user import Permission, Role, RolePermission, User, UserRole  # noqa: E402

# --------------------------------------------------------------------------- #
# 一、权限点（§8.3 清单，38 条）：(code, 名称/用途)
# module 由 code 的第一段推导（命名规则「模块:资源:动作」）。
# --------------------------------------------------------------------------- #
PERMISSIONS: list[tuple[str, str]] = [
    ("master:store:read", "门店查询"),
    ("master:store:write", "门店新建/修改(含配送节奏)"),
    ("master:sku:read", "SKU 查询/筛选"),
    ("master:sku:write", "SKU 新建(单位/换算/保质期)"),
    ("master:supplier:read", "供应商查询"),
    ("master:supplier:write", "供应商新建"),
    ("master:price:read", "历史当时价查询"),
    ("master:price:write", "价目新建(生效区间)"),
    ("purchase:create", "创建采购单"),
    ("purchase:read", "采购单查询"),
    ("purchase:receive", "收货并入批次库存+流水"),
    ("order:create", "门店提交要货单 draft"),
    ("order:update", "修改草稿明细"),
    ("order:confirm", "店长确认要货单生效"),
    ("order:cancel", "取消要货单(confirmed 前)"),
    ("order:read", "要货单查询(本店)"),
    ("agent:suggest", "生成要货建议快照"),
    ("agent:read", "查看建议快照与依据"),
    ("agent:apply", "采纳建议并生成 draft 要货单"),
    ("agent:pick_plan", "配货/分拣批次计划建议(只读)"),
    ("summary:generate", "按配送日汇总要货单"),
    ("summary:read", "汇总单查询"),
    ("pick:create", "生成分拣单(锁批次扣库存)"),
    ("pick:complete", "分拣完成"),
    ("delivery:create", "生成配送单(装车)"),
    ("delivery:read", "配送单查询(司机当日任务)"),
    ("delivery:depart", "发车"),
    ("sign:create", "签收(电子 POD,幂等)"),
    ("sign:read", "签收单详情"),
    ("loss:create", "门店提交报损"),
    ("loss:read", "报损查询"),
    ("stock:adjust", "审批报损/盘点差异并扣批次库存(写流水)"),
    ("reconcile:generate", "按周期生成对账单"),
    ("reconcile:read", "对账查询"),
    ("reconcile:confirm", "确认对账并记录外部差异"),
    ("report:profit", "门店盈亏核算"),
    ("report:kpi", "KPI 指标(损耗率/要货准确率/周转)"),
    (
        "system:permission:manage",
        "角色与权限点维护(预留，当前无对外端点，权限数据由种子 SQL 初始化)",
    ),
]

# --------------------------------------------------------------------------- #
# 二、角色与角色权限映射
# --------------------------------------------------------------------------- #
ROLES: list[tuple[str, str]] = [
    ("admin", "总部管理员"),
    ("ops", "总部运营"),
    ("driver", "司机"),
    ("store_manager", "店长"),
]

_ALL_CODES = [code for code, _ in PERMISSIONS]

# ops：主数据 + 采购收货 + 汇总分拣 + 报损审批 + 对账/报表（§8.3「默认角色」列）
_OPS_CODES = [
    "master:store:read",
    "master:sku:read",
    "master:sku:write",
    "master:supplier:read",
    "master:supplier:write",
    "master:price:read",
    "purchase:create",
    "purchase:read",
    "purchase:receive",
    "order:read",
    "agent:suggest",
    "agent:read",
    "agent:pick_plan",
    "summary:generate",
    "summary:read",
    "pick:create",
    "pick:complete",
    "delivery:create",
    "delivery:read",
    "sign:read",
    "loss:read",
    "stock:adjust",
    "reconcile:read",
    "report:profit",
    "report:kpi",
]

# store_manager：要货 + 报损 + 智能体建议 + 本店只读类（§8.3「默认角色」列）
_STORE_MANAGER_CODES = [
    "order:create",
    "order:update",
    "order:confirm",
    "order:cancel",
    "order:read",
    "agent:suggest",
    "agent:read",
    "agent:apply",
    "sign:create",
    "sign:read",
    "loss:create",
    # 店长签收前需查看配送单详情（§8.2 POST /deliveries/{id}/sign 的角色含 store_manager），
    # 缺该权限会导致店长能签收却打不开明细 → 签收功能不可用（已由冒烟测试发现并修复）
    "delivery:read",
]

# driver：配送签收类（§8.3「默认角色」列）
_DRIVER_CODES = [
    "delivery:read",
    "delivery:depart",
    "sign:create",
]

ROLE_PERMISSION_CODES: dict[str, list[str]] = {
    "admin": _ALL_CODES,  # 任务要求：admin 全量 38 条
    "ops": _OPS_CODES,
    "store_manager": _STORE_MANAGER_CODES,
    "driver": _DRIVER_CODES,
}

# --------------------------------------------------------------------------- #
# 三、测试用户（明文口令见模块顶部注释）
# --------------------------------------------------------------------------- #
USERS: list[dict] = [
    {
        "username": "admin",
        "password": "Admin@12345",
        "name": "总部管理员",
        "role": "admin",
        "store_no": None,
    },
    {
        "username": "ops",
        "password": "Ops@12345",
        "name": "总部运营",
        "role": "ops",
        "store_no": None,
    },
    {
        "username": "store01",
        "password": "Store@12345",
        "name": "潍坊001店长",
        "role": "store_manager",
        "store_no": "WF001",
    },
    {
        "username": "driver01",
        "password": "Driver@12345",
        "name": "司机01",
        "role": "driver",
        "store_no": None,
    },
]

# --------------------------------------------------------------------------- #
# 四、门店 8 家（daily / every_other_day 混合）
# --------------------------------------------------------------------------- #
STORES: list[dict] = [
    {"store_no": "WF001", "name": "潍坊001店", "region": "潍坊", "cycle": "daily"},
    {"store_no": "WF002", "name": "潍坊002店", "region": "潍坊", "cycle": "every_other_day"},
    {"store_no": "WF003", "name": "潍坊003店", "region": "潍坊", "cycle": "daily"},
    {"store_no": "JN001", "name": "济南001店", "region": "济南", "cycle": "daily"},
    {"store_no": "JN002", "name": "济南002店", "region": "济南", "cycle": "every_other_day"},
    {"store_no": "QD001", "name": "青岛001店", "region": "青岛", "cycle": "daily"},
    {"store_no": "QD002", "name": "青岛002店", "region": "青岛", "cycle": "every_other_day"},
    {"store_no": "QD003", "name": "青岛003店", "region": "青岛", "cycle": "daily"},
]
_ADDRESS = {
    "潍坊": "山东省潍坊市奎文区幸福路",
    "济南": "山东省济南市历下区泉城路",
    "青岛": "山东省青岛市市南区香港中路",
}

# --------------------------------------------------------------------------- #
# 五、SKU 16 个（馅料 8 / 面皮 2 / 调料 4 / 包材 2，全部直配）
# --------------------------------------------------------------------------- #
SKUS: list[dict] = [
    # 馅料：5kg/袋，基础单位 kg，换算 5，保质期 36-48 小时
    {"no": "XL001", "name": "虾仁三鲜馅", "cat": "馅料-海鲜", "spec": "5kg/袋",
     "unit": "袋", "base": "kg", "factor": "5", "shelf": 48},
    {"no": "XL002", "name": "白菜鲜肉馅", "cat": "馅料-肉馅", "spec": "5kg/袋",
     "unit": "袋", "base": "kg", "factor": "5", "shelf": 48},
    {"no": "XL003", "name": "韭菜鸡蛋馅", "cat": "馅料-素馅", "spec": "5kg/袋",
     "unit": "袋", "base": "kg", "factor": "5", "shelf": 36},
    {"no": "XL004", "name": "荠菜鲜肉馅", "cat": "馅料-肉馅", "spec": "5kg/袋",
     "unit": "袋", "base": "kg", "factor": "5", "shelf": 36},
    {"no": "XL005", "name": "酸菜猪肉馅", "cat": "馅料-肉馅", "spec": "5kg/袋",
     "unit": "袋", "base": "kg", "factor": "5", "shelf": 48},
    {"no": "XL006", "name": "鲅鱼馅", "cat": "馅料-海鲜", "spec": "5kg/袋",
     "unit": "袋", "base": "kg", "factor": "5", "shelf": 36},
    {"no": "XL007", "name": "酱肉丁馅", "cat": "馅料-肉馅", "spec": "5kg/袋",
     "unit": "袋", "base": "kg", "factor": "5", "shelf": 48},
    {"no": "XL008", "name": "黄瓜鸡蛋馅", "cat": "馅料-素馅", "spec": "5kg/袋",
     "unit": "袋", "base": "kg", "factor": "5", "shelf": 36},
    # 面皮：2.5kg/袋
    {"no": "MP001", "name": "精制饺子皮", "cat": "面皮", "spec": "2.5kg/袋",
     "unit": "袋", "base": "kg", "factor": "2.5", "shelf": 72},
    {"no": "MP002", "name": "菠菜饺子皮", "cat": "面皮", "spec": "2.5kg/袋",
     "unit": "袋", "base": "kg", "factor": "2.5", "shelf": 72},
    # 调料
    {"no": "TL001", "name": "金龙鱼油", "cat": "调料", "spec": "20L/桶",
     "unit": "桶", "base": "L", "factor": "20", "shelf": 8760},
    {"no": "TL002", "name": "饺子醋", "cat": "调料", "spec": "500ml×12瓶/箱",
     "unit": "箱", "base": "L", "factor": "6", "shelf": 8760},
    {"no": "TL003", "name": "辣椒油", "cat": "调料", "spec": "5L/桶",
     "unit": "桶", "base": "L", "factor": "5", "shelf": 8760},
    {"no": "TL004", "name": "酱油", "cat": "调料", "spec": "1.8L×6瓶/箱",
     "unit": "箱", "base": "L", "factor": "10.8", "shelf": 8760},
    # 包材
    {"no": "BC001", "name": "打包盒", "cat": "包材", "spec": "500个/箱",
     "unit": "箱", "base": "个", "factor": "500", "shelf": 8760},
    {"no": "BC002", "name": "餐具套装", "cat": "包材", "spec": "1000套/箱",
     "unit": "箱", "base": "套", "factor": "1000", "shelf": 8760},
]

# --------------------------------------------------------------------------- #
# 六、供应商 6 家（账期 7-30 天）
# --------------------------------------------------------------------------- #
SUPPLIERS: list[dict] = [
    {"no": "SP001", "name": "双汇", "contact": "王经理", "phone": "13800000001", "terms": 15},
    {"no": "SP002", "name": "金锣", "contact": "李经理", "phone": "13800000002", "terms": 20},
    {"no": "SP003", "name": "得利斯", "contact": "赵经理", "phone": "13800000003", "terms": 15},
    {"no": "SP004", "name": "潍坊华丰蔬菜", "contact": "孙经理", "phone": "13800000004", "terms": 7},
    {"no": "SP005", "name": "海天", "contact": "周经理", "phone": "13800000005", "terms": 30},
    {"no": "SP006", "name": "恒信包装", "contact": "吴经理", "phone": "13800000006", "terms": 30},
]

# --------------------------------------------------------------------------- #
# 七、价目表：每个 SKU 采购价 1 条 + 调拨价 1 条（生效区间自固定日 2026-10-01 起）
# 单位均为「元/订货单位」。调拨价 = 总部→门店内部结算价，应不低于采购价。
# --------------------------------------------------------------------------- #
PRICE_FROM = date(2026, 10, 1)
PRICES: dict[str, tuple[str, str]] = {
    "XL001": ("32.00", "38.00"),
    "XL002": ("22.00", "27.00"),
    "XL003": ("18.00", "23.00"),
    "XL004": ("20.00", "25.00"),
    "XL005": ("19.00", "24.00"),
    "XL006": ("28.00", "34.00"),
    "XL007": ("24.00", "29.00"),
    "XL008": ("16.00", "21.00"),
    "MP001": ("12.00", "15.00"),
    "MP002": ("13.00", "16.00"),
    "TL001": ("180.00", "200.00"),
    "TL002": ("60.00", "70.00"),
    "TL003": ("55.00", "65.00"),
    "TL004": ("48.00", "58.00"),
    "BC001": ("90.00", "100.00"),
    "BC002": ("70.00", "80.00"),
}

# --------------------------------------------------------------------------- #
# 八、总部仓批次库存：6 个常用 SKU 各 1 个批次
# 批次号固定以 PC20261012 开头；生产日期取运行当天，效期动态取「当天 + 2 天」
# （运行时约 2026-10-14）；数量为 30-100 的基础单位且取 5 的整数倍（整袋）。
# --------------------------------------------------------------------------- #
BATCHES: list[tuple[str, str]] = [
    ("XL001", "100"),
    ("XL002", "80"),
    ("XL003", "75"),
    ("XL004", "60"),
    ("MP001", "50"),
    ("MP002", "40"),
]

# --------------------------------------------------------------------------- #
# 九、示例要货单 2 张（潍坊001店）：draft（明天）+ confirmed（今天，总部已确认）
# 明细数量为「订货单位」（袋/箱），qty_base = qty_unit × convert_factor。
# 注意：order_item 表无单价列（价格按价目表取当时价，见 §7.3），故此处只落数量。
# --------------------------------------------------------------------------- #
ORDERS: list[dict] = [
    {
        "idempotency_key": "seed-order-draft-WF001",
        "store_no": "WF001",
        "status": "draft",
        "day_offset": 1,
        "items": [("XL001", "6"), ("XL002", "8"), ("MP001", "10"), ("MP002", "5")],
    },
    {
        "idempotency_key": "seed-order-confirmed-WF001",
        "store_no": "WF001",
        "status": "confirmed",
        "day_offset": 0,
        "items": [("XL002", "10"), ("XL003", "6"), ("XL004", "5"), ("MP001", "12"), ("BC001", "1")],
    },
]

STATUS_ENABLED = 1


# --------------------------------------------------------------------------- #
# 统计器与幂等写入辅助
# --------------------------------------------------------------------------- #
class Counters:
    """按表累计「新增 / 跳过」，结束时打印中文摘要。"""

    def __init__(self) -> None:
        self.data: dict[str, dict[str, int]] = {}

    def bump(self, label: str, inserted: bool) -> None:
        rec = self.data.setdefault(label, {"inserted": 0, "skipped": 0})
        rec["inserted" if inserted else "skipped"] += 1

    def totals(self) -> tuple[int, int]:
        inserted = sum(rec["inserted"] for rec in self.data.values())
        skipped = sum(rec["skipped"] for rec in self.data.values())
        return inserted, skipped


def _ensure(
    session: Session,
    counters: Counters,
    label: str,
    model: type,
    lookup: dict,
    values: dict | None = None,
):
    """先按业务唯一键查，命中返回 (obj, False)；否则插入并返回 (obj, True)。"""
    obj = session.scalar(select(model).filter_by(**lookup))
    if obj is not None:
        counters.bump(label, inserted=False)
        return obj, False
    data = dict(lookup)
    if values:
        data.update(values)
    obj = model(**data)
    session.add(obj)
    session.flush()
    counters.bump(label, inserted=True)
    return obj, True


def _sentinel(**filters) -> dict:
    """为软删表补上 deleted_at 哨兵条件（只命中未删除行）。"""
    return {**filters, "deleted_at": SOFT_DELETE_SENTINEL}


# --------------------------------------------------------------------------- #
# 各步播种
# --------------------------------------------------------------------------- #
def seed_permissions(session: Session, counters: Counters) -> dict[str, Permission]:
    label = "权限点 permission"
    result: dict[str, Permission] = {}
    for code, name in PERMISSIONS:
        module = code.split(":", 1)[0]
        obj, _ = _ensure(
            session,
            counters,
            label,
            Permission,
            lookup={"code": code},
            values={"name": name, "module": module, "description": name, "status": STATUS_ENABLED},
        )
        result[code] = obj
    return result


def seed_roles(session: Session, counters: Counters) -> dict[str, Role]:
    label = "角色 role"
    result: dict[str, Role] = {}
    for code, name in ROLES:
        obj, _ = _ensure(
            session,
            counters,
            label,
            Role,
            lookup={"code": code},
            values={"name": name, "status": STATUS_ENABLED},
        )
        result[code] = obj
    return result


def seed_stores(session: Session, counters: Counters, created_by: int | None) -> dict[str, Store]:
    label = "门店 store"
    result: dict[str, Store] = {}
    for item in STORES:
        region = item["region"]
        address = f"{_ADDRESS[region]}（{item['name']}）"
        obj, _ = _ensure(
            session,
            counters,
            label,
            Store,
            lookup=_sentinel(store_no=item["store_no"]),
            values={
                "name": item["name"],
                "region": region,
                "address": address,
                "contact_name": f"{item['name']}负责人",
                "contact_phone": "0536-8888000",
                "delivery_cycle": item["cycle"],
                "status": STATUS_ENABLED,
                "created_by": created_by,
                "updated_by": created_by,
            },
        )
        result[item["store_no"]] = obj
    return result


def seed_users(
    session: Session,
    counters: Counters,
    roles: dict[str, Role],
    stores: dict[str, Store],
) -> dict[str, User]:
    label = "用户 user"
    label_ur = "用户角色 user_role"
    result: dict[str, User] = {}
    for item in USERS:
        store_id = stores[item["store_no"]].id if item["store_no"] else None
        existing = session.scalar(
            select(User).filter_by(username=item["username"], deleted_at=SOFT_DELETE_SENTINEL)
        )
        if existing is not None:
            counters.bump(label, inserted=False)
            user = existing
        else:
            user = User(
                username=item["username"],
                password_hash=hash_password(item["password"]),
                name=item["name"],
                store_id=store_id,
                status=STATUS_ENABLED,
                deleted_at=SOFT_DELETE_SENTINEL,
            )
            session.add(user)
            session.flush()
            counters.bump(label, inserted=True)
        result[item["username"]] = user
        _ensure(
            session,
            counters,
            label_ur,
            UserRole,
            lookup={"user_id": user.id, "role_id": roles[item["role"]].id},
        )
    return result


def seed_role_permissions(
    session: Session,
    counters: Counters,
    roles: dict[str, Role],
    perms: dict[str, Permission],
    created_by: int | None,
) -> None:
    label = "角色权限 role_permission"
    for role_code, codes in ROLE_PERMISSION_CODES.items():
        role = roles[role_code]
        for code in codes:
            _ensure(
                session,
                counters,
                label,
                RolePermission,
                lookup={"role_id": role.id, "permission_id": perms[code].id},
                values={"created_by": created_by},
            )


def seed_suppliers(
    session: Session, counters: Counters, created_by: int | None
) -> dict[str, Supplier]:
    label = "供应商 supplier"
    result: dict[str, Supplier] = {}
    for item in SUPPLIERS:
        obj, _ = _ensure(
            session,
            counters,
            label,
            Supplier,
            lookup=_sentinel(supplier_no=item["no"]),
            values={
                "name": item["name"],
                "contact_name": item["contact"],
                "contact_phone": item["phone"],
                "payment_terms": item["terms"],
                "status": STATUS_ENABLED,
                "created_by": created_by,
                "updated_by": created_by,
            },
        )
        result[item["no"]] = obj
    return result


def seed_skus(session: Session, counters: Counters, created_by: int | None) -> dict[str, Sku]:
    label = "SKU sku"
    result: dict[str, Sku] = {}
    for item in SKUS:
        obj, _ = _ensure(
            session,
            counters,
            label,
            Sku,
            lookup=_sentinel(sku_no=item["no"]),
            values={
                "name": item["name"],
                "category": item["cat"],
                "spec": item["spec"],
                "unit": item["unit"],
                "base_unit": item["base"],
                "convert_factor": Decimal(item["factor"]),
                "shelf_life_hours": item["shelf"],
                "supply_type": "direct",
                "status": STATUS_ENABLED,
                "created_by": created_by,
                "updated_by": created_by,
            },
        )
        result[item["no"]] = obj
    return result


def seed_prices(
    session: Session,
    counters: Counters,
    skus: dict[str, Sku],
    created_by: int | None,
) -> None:
    label = "价目表 price"
    for sku_no, (purchase, transfer) in PRICES.items():
        sku = skus[sku_no]
        for price_type, amount in (("purchase", purchase), ("transfer", transfer)):
            _ensure(
                session,
                counters,
                label,
                Price,
                lookup=_sentinel(
                    sku_id=sku.id,
                    price_type=price_type,
                    effective_from=PRICE_FROM,
                ),
                values={
                    "price": Decimal(amount),
                    "effective_to": None,
                    "created_by": created_by,
                    "updated_by": created_by,
                },
            )


def seed_batch_stocks(
    session: Session,
    counters: Counters,
    skus: dict[str, Sku],
    created_by: int | None,
    today: date,
) -> None:
    label = "批次库存 batch_stock"
    for seq, (sku_no, qty) in enumerate(BATCHES, start=1):
        sku = skus[sku_no]
        batch_no = f"PC20261012-{seq:02d}"
        expire_at = datetime.combine(today + timedelta(days=2), time(hour=18, minute=0))
        _ensure(
            session,
            counters,
            label,
            BatchStock,
            lookup=_sentinel(store_id=0, sku_id=sku.id, batch_no=batch_no),
            values={
                "qty_base": Decimal(qty),
                "produced_at": today,
                "expire_at": expire_at,
                "version": 0,
                "created_by": created_by,
                "updated_by": created_by,
            },
        )


def seed_orders(
    session: Session,
    counters: Counters,
    skus: dict[str, Sku],
    stores: dict[str, Store],
    users: dict[str, User],
    today: date,
    now: datetime,
) -> None:
    label_head = "要货单头 order_head"
    label_item = "要货明细 order_item"
    for seq, spec in enumerate(ORDERS, start=1):
        require_date = today + timedelta(days=spec["day_offset"])
        store = stores[spec["store_no"]]
        order_no = f"XH{today:%Y%m%d}{seq:02d}"
        existing = session.scalar(
            select(OrderHead).filter_by(
                idempotency_key=spec["idempotency_key"], deleted_at=SOFT_DELETE_SENTINEL
            )
        )
        if existing is not None:
            counters.bump(label_head, inserted=False)
            for _ in spec["items"]:
                counters.bump(label_item, inserted=False)
            continue

        confirmed = spec["status"] == "confirmed"
        order = OrderHead(
            order_no=order_no,
            store_id=store.id,
            require_date=require_date,
            status=spec["status"],
            source="manual",
            confirm_by=users["ops"].id if confirmed else None,
            confirm_at=now if confirmed else None,
            idempotency_key=spec["idempotency_key"],
            version=0,
            deleted_at=SOFT_DELETE_SENTINEL,
            created_by=users["store01"].id,
            updated_by=users["store01"].id,
        )
        session.add(order)
        session.flush()
        counters.bump(label_head, inserted=True)

        for sku_no, qty_unit in spec["items"]:
            sku = skus[sku_no]
            qty = Decimal(qty_unit)
            session.add(
                OrderItem(
                    order_id=order.id,
                    sku_id=sku.id,
                    qty_base=(qty * sku.convert_factor).quantize(Decimal("0.001")),
                    qty_unit=qty,
                    unit=sku.unit,
                    batch_no=None,
                    created_by=users["store01"].id,
                    updated_by=users["store01"].id,
                )
            )
            session.flush()
            counters.bump(label_item, inserted=True)


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def _validate_definition() -> None:
    """离线自检：权限点 38 条、角色映射引用的 code 均存在。"""
    if len(PERMISSIONS) != 38:
        raise RuntimeError(f"permission 清单应为 38 条，当前 {len(PERMISSIONS)} 条")
    codes = {code for code, _ in PERMISSIONS}
    if len(codes) != len(PERMISSIONS):
        raise RuntimeError("permission code 存在重复")
    if set(ROLE_PERMISSION_CODES) != {code for code, _ in ROLES}:
        raise RuntimeError("角色权限映射与角色清单不一致")
    for role_code, role_codes in ROLE_PERMISSION_CODES.items():
        missing = [code for code in role_codes if code not in codes]
        if missing:
            raise RuntimeError(f"角色 {role_code} 引用了不存在的权限点: {missing}")


def print_summary(counters: Counters) -> None:
    print("=" * 64)
    print("种子数据初始化完成（幂等：已存在的数据自动跳过）")
    print("-" * 64)
    for label, rec in counters.data.items():
        print(f"{label:<24} 新增 {rec['inserted']:>3} 条，跳过 {rec['skipped']:>3} 条")
    inserted, skipped = counters.totals()
    print("-" * 64)
    print(f"{'合计':<24} 新增 {inserted:>3} 条，跳过 {skipped:>3} 条")
    print("-" * 64)
    print("测试账号（明文口令仅限开发/测试环境）：")
    for item in USERS:
        print(f"  {item['username']:<9} {item['password']:<12} {item['name']}")
    print("=" * 64)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="念家鲜饺供应链系统种子数据初始化（幂等）")
    parser.parse_args(argv)

    _validate_definition()

    engine = create_engine(settings.database_url, echo=settings.DB_ECHO, pool_pre_ping=True)
    session_factory = sessionmaker(bind=engine, autoflush=True, expire_on_commit=False)

    counters = Counters()
    today = date.today()
    now = datetime.now()

    with session_factory() as session:
        try:
            perms = seed_permissions(session, counters)
            roles = seed_roles(session, counters)
            stores = seed_stores(session, counters, created_by=None)
            users = seed_users(session, counters, roles, stores)
            admin_id = users["admin"].id
            seed_role_permissions(session, counters, roles, perms, created_by=admin_id)
            seed_suppliers(session, counters, created_by=admin_id)
            skus = seed_skus(session, counters, created_by=admin_id)
            seed_prices(session, counters, skus, created_by=admin_id)
            seed_batch_stocks(session, counters, skus, created_by=admin_id, today=today)
            seed_orders(session, counters, skus, stores, users, today=today, now=now)
            session.commit()
        except Exception:
            session.rollback()
            raise
    engine.dispose()

    print_summary(counters)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



