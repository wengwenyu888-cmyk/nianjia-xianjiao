"""SQLAlchemy ORM 模型包（26 张表，对应 docs/02 v0.3.1 §7 的 DDL）。

导入本包即把全部表注册到 Base.metadata，Alembic autogenerate / env.py 依赖这一点。
表清单（26）：
  主数据(4)      store / supplier / sku / price
  库存(2)        batch_stock / batch_flow
  采购(2)        purchase_order / purchase_order_item
  要货(3)        order_head / order_item / agent_suggestion
  汇总分拣(4)    summary / summary_item / pick / pick_item
  配送签收(4)    delivery / delivery_item / sign / sign_item
  报损对账(2)    loss / reconcile
  用户权限(5)    user / role / permission / user_role / role_permission
"""

from app.model.base import (
    AuditMixin,
    Base,
    IdMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)
from app.model.delivery import Delivery, DeliveryItem, Sign, SignItem
from app.model.inventory import BatchFlow, BatchStock
from app.model.loss import Loss, Reconcile
from app.model.order import AgentSuggestion, OrderHead, OrderItem
from app.model.purchase import PurchaseOrder, PurchaseOrderItem
from app.model.store import Price, Sku, Store, Supplier
from app.model.summary import Pick, PickItem, Summary, SummaryItem
from app.model.user import Permission, Role, RolePermission, User, UserRole

__all__ = [
    # base / Mixin
    "Base",
    "IdMixin",
    "TimestampMixin",
    "AuditMixin",
    "SoftDeleteMixin",
    "VersionMixin",
    # 主数据（§7.1）
    "Store",
    "Supplier",
    "Sku",
    "Price",
    # 库存与采购（§7.2）
    "BatchStock",
    "BatchFlow",
    "PurchaseOrder",
    "PurchaseOrderItem",
    # 要货（§7.3）
    "OrderHead",
    "OrderItem",
    "AgentSuggestion",
    # 汇总与分拣（§7.3/§7.4）
    "Summary",
    "SummaryItem",
    "Pick",
    "PickItem",
    # 配送与签收（§7.4）
    "Delivery",
    "DeliveryItem",
    "Sign",
    "SignItem",
    # 报损与对账（§7.5）
    "Loss",
    "Reconcile",
    # 用户与权限（§7.6）
    "User",
    "Role",
    "Permission",
    "UserRole",
    "RolePermission",
]
