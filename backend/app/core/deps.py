"""依赖注入：数据库会话、当前用户、权限点校验、分页参数、服务提供者。

约定：api 层通过这里拿会话、身份与 service，不直接 new Session、不自行解析 Token；
model 只在本文件内按 id 加载用户与权限，api 层始终只接触 schema 与 dict。
"""

from __future__ import annotations

from collections.abc import Iterator
from enum import StrEnum
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.exceptions import PermissionDeniedError
from app.model.base import SOFT_DELETE_SENTINEL
from app.model.user import Permission, Role, RolePermission, User, UserRole

# --------------------------------------------------------------------------- 数据库
# 骨架用同步引擎 + 连接池；生产读多写少时可另挂只读实例
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,  # 取连接前 ping，避免 MySQL 空闲断连
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    echo=settings.DB_ECHO,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """请求级数据库会话：正常提交、异常回滚、最终关闭。"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


DbSession = Annotated[Session, Depends(get_db)]


# --------------------------------------------------------------------------- 权限点
class PermissionCode(StrEnum):
    """全部权限点（§8.3，39 条；取值与 seed/seed.py 的 PERMISSIONS 逐字一致）。

    判定单元是权限点，角色只是权限点集合；本枚举是代码侧唯一定义处，
    api 层一律 require_permission(PermissionCode.XXX)，不再各自声明本地 StrEnum。
    """

    # 主数据 master（8）
    STORE_READ = "master:store:read"
    STORE_WRITE = "master:store:write"
    SKU_READ = "master:sku:read"
    SKU_WRITE = "master:sku:write"
    SUPPLIER_READ = "master:supplier:read"
    SUPPLIER_WRITE = "master:supplier:write"
    PRICE_READ = "master:price:read"
    PRICE_WRITE = "master:price:write"

    # 采购 purchase（3）
    PURCHASE_CREATE = "purchase:create"
    PURCHASE_READ = "purchase:read"
    PURCHASE_RECEIVE = "purchase:receive"

    # 要货 order（5）
    ORDER_CREATE = "order:create"
    ORDER_UPDATE = "order:update"
    ORDER_CONFIRM = "order:confirm"
    ORDER_CANCEL = "order:cancel"
    ORDER_READ = "order:read"

    # 智能体 agent（4）
    AGENT_SUGGEST = "agent:suggest"
    AGENT_READ = "agent:read"
    AGENT_APPLY = "agent:apply"
    AGENT_PICK_PLAN = "agent:pick_plan"

    # 汇总 summary（2）
    SUMMARY_GENERATE = "summary:generate"
    SUMMARY_READ = "summary:read"

    # 分拣 pick（2）
    PICK_CREATE = "pick:create"
    PICK_COMPLETE = "pick:complete"

    # 配送 delivery（3）
    DELIVERY_CREATE = "delivery:create"
    DELIVERY_READ = "delivery:read"
    DELIVERY_DEPART = "delivery:depart"

    # 签收 sign（2）
    SIGN_CREATE = "sign:create"
    SIGN_READ = "sign:read"

    # 报损 loss（2）
    LOSS_CREATE = "loss:create"
    LOSS_READ = "loss:read"

    # 库存 stock（2）
    STOCK_READ = "stock:read"
    STOCK_ADJUST = "stock:adjust"

    # 对账 reconcile（3）
    RECONCILE_GENERATE = "reconcile:generate"
    RECONCILE_READ = "reconcile:read"
    RECONCILE_CONFIRM = "reconcile:confirm"

    # 报表 report（2）
    REPORT_PROFIT = "report:profit"
    REPORT_KPI = "report:kpi"

    # 系统 system（1，预留：当前无对外端点）
    SYSTEM_PERMISSION_MANAGE = "system:permission:manage"


# 内置角色 → 权限点（§8.3「默认角色」列，与 seed/seed.py 的 ROLE_PERMISSION_CODES 对齐）。
# 生产以数据库 role_permission 为准（seed 写入的权威授权）；本表仅为未 seed 环境的兜底，
# 运行时与库中授权取并集（见 load_user_authorities）。
# 条数：admin 39 / ops 26 / store_manager 12 / driver 3。
ROLE_PERMISSIONS: dict[str, frozenset[PermissionCode]] = {
    # admin：全量 39 条
    "admin": frozenset(PermissionCode),
    # ops（26）：主数据 + 采购收货 + 汇总分拣 + 报损审批 + 对账/报表
    "ops": frozenset(
        {
            PermissionCode.STORE_READ,
            PermissionCode.SKU_READ,
            PermissionCode.SKU_WRITE,
            PermissionCode.SUPPLIER_READ,
            PermissionCode.SUPPLIER_WRITE,
            PermissionCode.PRICE_READ,
            PermissionCode.PURCHASE_CREATE,
            PermissionCode.PURCHASE_READ,
            PermissionCode.PURCHASE_RECEIVE,
            PermissionCode.ORDER_READ,
            PermissionCode.AGENT_SUGGEST,
            PermissionCode.AGENT_READ,
            PermissionCode.AGENT_PICK_PLAN,
            PermissionCode.SUMMARY_GENERATE,
            PermissionCode.SUMMARY_READ,
            PermissionCode.PICK_CREATE,
            PermissionCode.PICK_COMPLETE,
            PermissionCode.DELIVERY_CREATE,
            PermissionCode.DELIVERY_READ,
            PermissionCode.SIGN_READ,
            PermissionCode.LOSS_READ,
            PermissionCode.STOCK_READ,
            PermissionCode.STOCK_ADJUST,
            PermissionCode.RECONCILE_READ,
            PermissionCode.REPORT_PROFIT,
            PermissionCode.REPORT_KPI,
        }
    ),
    # store_manager（12）：要货 + 报损 + 智能体建议 + 配送/签收只读；
    # delivery:read 为 2026-10-12 补齐（店长签收前需查看配送单明细，见 §8.3）
    "store_manager": frozenset(
        {
            PermissionCode.ORDER_CREATE,
            PermissionCode.ORDER_UPDATE,
            PermissionCode.ORDER_CONFIRM,
            PermissionCode.ORDER_CANCEL,
            PermissionCode.ORDER_READ,
            PermissionCode.AGENT_SUGGEST,
            PermissionCode.AGENT_READ,
            PermissionCode.AGENT_APPLY,
            PermissionCode.SIGN_CREATE,
            PermissionCode.SIGN_READ,
            PermissionCode.LOSS_CREATE,
            PermissionCode.DELIVERY_READ,
        }
    ),
    # driver（3）：配送签收
    "driver": frozenset(
        {
            PermissionCode.DELIVERY_READ,
            PermissionCode.DELIVERY_DEPART,
            PermissionCode.SIGN_CREATE,
        }
    ),
}

# --------------------------------------------------------------------------- 鉴权
# auto_error=False：自行抛 401，保证错误响应体与项目统一格式一致
bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    """401 统一构造：带上 WWW-Authenticate，由全局处理器转成 40100。"""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def load_user_by_id(db: Session, user_id: int) -> User | None:
    """按 id 加载「未软删且启用」的用户；数据口径与登录校验保持一致。"""
    return db.execute(
        select(User).where(
            User.id == user_id,
            User.deleted_at == SOFT_DELETE_SENTINEL,
            User.status == 1,
        )
    ).scalar_one_or_none()


def load_user_by_username(db: Session, username: str) -> User | None:
    """按登录名加载「未软删且启用」的用户；软删/停用一律视为不存在（防枚举）。"""
    return db.execute(
        select(User).where(
            User.username == username,
            User.deleted_at == SOFT_DELETE_SENTINEL,
            User.status == 1,
        )
    ).scalar_one_or_none()


def load_user_authorities(db: Session, user_id: int) -> tuple[list[str], list[str]]:
    """取用户角色码与权限点码并集（user→user_role→role_permission→permission）。

    Returns:
        (roles, permissions)：角色码列表；权限点码去重排序后的列表。
    """
    roles = list(
        db.scalars(
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id, Role.status == 1)
        ).all()
    )
    granted: set[str] = set(
        db.scalars(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user_id, Permission.status == 1)
        ).all()
    )
    for role_code in roles:
        granted.update(code.value for code in ROLE_PERMISSIONS.get(role_code, frozenset()))
    return roles, sorted(granted)


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> dict[str, Any]:
    """解析 Bearer JWT，并据 user 表加载用户（含 store_id 数据范围与权限并集）。

    Returns:
        dict: user_id / username / name / store_id / role / roles / permissions

    Raises:
        HTTPException 401: 未带令牌、令牌非法或用户不存在/已停用。
    """
    # 延迟导入：未安装 python-jose 时仍可完成编译与路由装配检查
    from app.core.security import InvalidTokenError, decode_token

    if credentials is None or not credentials.credentials:
        raise _unauthorized("未登录或缺少访问令牌")
    try:
        payload = decode_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise _unauthorized(str(exc)) from exc

    if payload.get("type") != "access":
        raise _unauthorized("令牌类型不正确")

    user_id = int(payload["sub"])
    user = load_user_by_id(db, user_id)
    if user is None:
        raise _unauthorized("用户不存在或已停用")

    roles, permissions = load_user_authorities(db, user.id)

    return {
        "user_id": user.id,
        "username": user.username,
        "name": user.name,
        "store_id": user.store_id,  # 数据范围：非 NULL 时查询强制注入本店条件
        "role": payload.get("role", ""),
        "roles": roles,
        "permissions": permissions,
    }


CurrentUser = Annotated[dict[str, Any], Depends(get_current_user)]


def require_permission(*codes: PermissionCode) -> Any:
    """按 §8.3 权限点校验：所需权限点 ∈ 用户权限并集，否则 40300。"""

    def checker(user: CurrentUser) -> dict[str, Any]:
        granted = set(user.get("permissions") or ())
        missing = {str(code) for code in codes} - granted
        if missing:
            raise PermissionDeniedError(f"缺少权限点：{', '.join(sorted(missing))}")
        return user

    return checker


def require_hq(user: CurrentUser) -> dict[str, Any]:
    """总部专用接口守卫。"""
    if user.get("role") != "hq":
        raise PermissionDeniedError("需要总部账号权限")
    return user


HqUser = Annotated[dict[str, Any], Depends(require_hq)]


# --------------------------------------------------------------------------- 服务提供者
def get_master_service() -> Any:
    """主数据服务提供者：api 经依赖注入取 service，测试可整体替换为 fake。"""
    from app.service import store_service

    return store_service


MasterService = Annotated[Any, Depends(get_master_service)]


def get_auth_service() -> Any:
    """认证服务提供者：登录校验与 JWT 签发；测试可整体替换为 fake。"""
    from app.service import auth_service

    return auth_service


AuthService = Annotated[Any, Depends(get_auth_service)]


# --------------------------------------------------------------------------- 分页
class PageParams:
    """统一分页参数：page 从 1 开始，page_size 上限 200（§8.1）。"""

    def __init__(
        self,
        page: int = Query(1, ge=1, description="页码，从 1 开始"),
        page_size: int = Query(20, ge=1, le=200, description="每页条数，最大 200"),
    ) -> None:
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


Pagination = Annotated[PageParams, Depends()]
