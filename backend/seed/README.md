# backend/seed —— 种子数据初始化

本目录只放「开发/测试用」种子数据脚本，不参与应用运行时。生产环境禁止使用，
生产权限数据由发布流程 / 种子 SQL 初始化（见 docs/02-架构与模块设计.md §8.3）。

## 文件

| 文件 | 说明 |
|---|---|
| `seed.py` | 幂等种子脚本：权限点 → 角色 → 门店 → 用户 → 角色权限 → 供应商 → SKU → 价目表 → 批次库存 → 示例要货单 |
| `__init__.py` | 使 `seed` 可作为包被 `python -m seed.seed` 加载 |

## 怎么跑

**前置**：MySQL 已启动、库表已建（`alembic upgrade head`）、`backend/.env` 已配置
数据库连接（或设 `DATABASE_URL`）。

```bash
cd backend

# 方式一：uv（推荐，自动使用项目依赖）
uv run python -m seed.seed

# 方式二：裸 python（需已装依赖，且当前目录为 backend/）
python seed/seed.py
```

脚本会自动把 `backend/` 加入 `sys.path`，因此不依赖 `PYTHONPATH`。

## 测试账号

| 用户名 | 明文口令 | display_name | 角色 | 数据范围 |
|---|---|---|---|---|
| `admin` | `Admin@12345` | 总部管理员 | admin | 总部（store_id 为空，全门店） |
| `ops` | `Ops@12345` | 总部运营 | ops | 总部 |
| `store01` | `Store@12345` | 潍坊001店长 | store_manager | 绑定 WF001（潍坊001店） |
| `driver01` | `Driver@12345` | 司机01 | driver | 总部（司机账号不绑门店） |

口令以 bcrypt 哈希入库（`app.core.security.hash_password`），明文只写在
`seed.py` 顶部注释与本表，**仅限开发/测试环境**。

## 幂等策略

脚本可安全重复执行，重复执行时「已存在的数据跳过、不覆盖、不报错」：

- **先查后插**：每类数据按业务唯一键查询，命中即跳过。
  - 软删表（store / supplier / sku / price / batch_stock / order_head / user）查询时
    固定带上 `deleted_at = SOFT_DELETE_SENTINEL`（只命中未删除行）；
  - 各表唯一键：permission.code、role.code、store.store_no、supplier.supplier_no、
    sku.sku_no、price(sku_id, price_type, effective_from)、
    batch_stock(store_id, sku_id, batch_no)、(user_id, role_id)、(role_id, permission_id)；
  - 要货单先按 `idempotency_key`（`seed-` 前缀）判断，同一张单不重复落库。
- **不刷新已有数据**：已存在的行保持原值，脚本不做 UPDATE（避免覆盖人工调整）；
  需要重置请先自行清表再执行。
- **单事务提交**：全部步骤在一个事务里完成，中途异常整体回滚，不留半套数据。
- **口令惰性哈希**：用户已存在时不再计算 bcrypt，重复执行更快。

## 数据规模

- 权限点 38 条（§8.3 全量）、角色 4 个、角色权限映射 admin 38 / ops 25 /
  store_manager 11 / driver 3（共 77 条）；
- 门店 8 家（潍坊 3、济南 2、青岛 3；daily 与 every_other_day 混合）；
- SKU 16 个（馅料 8、面皮 2、调料 4、包材 2，全部 supply_type=direct）；
- 供应商 6 家（账期 7-30 天）；
- 价目表 32 条（16 个 SKU × 采购价/调拨价各 1，生效自 2026-10-01）；
- 总部仓（store_id=0）批次库存 6 条（批次号 `PC20261012-*`，效期取运行当天 +2 天）；
- 潍坊001店示例要货单 2 张（draft 明天 / confirmed 今天），明细 4 + 5 行。

## 说明与已知取舍

- **日期动态计算**：要货单需求日按运行时当天/次日推算，批次效期取「当天 + 2 天」，
  脚本内不写死“今天”。仅批次号前缀 `PC20261012` 与价目生效日 `2026-10-01` 固定。
- **order_item 无单价列**：§7.3 的 `order_item` 只有数量与单位，单价/金额由
  `price` 价目表按「当时价」取用，因此示例明细只落数量，不落单价。
- **插入顺序调整**：门店先于用户播种，因为 `store01` 店长需绑定 WF001 的
  `store_id`（`user.store_id` 是硬依赖）。
- **admin 权限为全量 38 条**：§8.3「默认角色」列中 admin 未逐一列出仅店长可做的
  动作，本脚本按需求让 admin 取全量；ops / store_manager / driver 严格按该列展开。
