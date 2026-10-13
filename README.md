# 念家鲜饺供应链系统（nianjia-xianjiao）

门店要货到签收对账的闭环系统：门店按「斤」要货 → 总部汇总 → 分拣称重 → 司机配送 →
门店电子签收 → 门店盈亏对账。

- 技术栈：FastAPI（Python 3.12）+ MySQL 8 + Vue3 / Element Plus（响应式网页端：总部后台 + 门店端 + 司机端）
- 部署定稿：轻量应用服务器 + Docker 起步，数据库用云 RDS MySQL；门店量增长后再迁 TKE
- 仓库：GitHub 私有仓库；规范以 `docs/05-工程基座方案.md` 为唯一权威

---

## 1. 目录说明

```text
backend/        FastAPI 服务（总部 API，三端共用）
  app/api/      路由层：只做参数校验、鉴权、调 service、组响应
  app/core/     横切：config / security / deps / logging / exceptions
  app/model/    SQLAlchemy ORM（表结构唯一事实源）
  app/schema/   Pydantic 契约（统一响应、分页、枚举）
  app/service/  业务逻辑（唯一事务边界、状态机、幂等）
  app/integration/ 外部对接（银豹 / 金蝶 / 管家婆 / LLM）
  app/utils/    纯函数（单位换算等）
  alembic/      数据库迁移（只前进不回滚）
  tests/        pytest：unit + api（TestClient）
frontend-web/   响应式网页端：总部后台 + 门店端 + 司机端（Vue3 + Element Plus + Vite + Pinia + vue-router）
deploy/         Dockerfile、docker-compose.yml、nginx.conf、.env.example
docs/           业务手册、架构设计、里程碑、工程基座方案
```

分层铁律（详见 docs/05 第 1 节）：`api` 不写 SQL 与业务判断；`service` 是唯一事务边界；
`model` 不被 `api` 直接导入；对外一律返回 schema，禁止直接返回 ORM 对象。

---

## 2. 本地启动（三端）

### 2.0 前置

Git、Python 3.12、[uv](https://docs.astral.sh/uv/)、Node 20 + pnpm、Docker。

### 2.1 环境变量

```bash
copy .env.example .env                 # Windows
cp .env.example .env                   # macOS / Linux
copy backend\.env.example backend\.env
copy frontend-web\.env.example frontend-web\.env.development
copy deploy\.env.example deploy\.env
```

`.env` 已在 `.gitignore` 中，密钥（数据库密码 / JWT 密钥 / LLM Key）绝不入库。

### 2.2 起 MySQL（本地中间件）

```bash
docker compose -f deploy/docker-compose.yml up -d mysql
```

### 2.3 后端

```bash
cd backend
uv sync                                  # 按 uv.lock 装依赖
uv run alembic upgrade head               # 迁移到最新（当前骨架无表，建库后即可跑通）
uv run uvicorn app.main:app --reload --port 8000
# 接口文档：http://127.0.0.1:8000/docs
# 健康检查：http://127.0.0.1:8000/api/v1/health → {"code":0,...,"data":{"status":"ok"}}
```

测试与静态检查：

```bash
cd backend
uv run pytest                 # 单元 + 接口测试（健康检查不连数据库）
uv run ruff check .           # lint
uv run ruff format --check .  # 格式
uv run mypy app/core app/service
```

### 2.4 前端后台

```bash
cd frontend-web
pnpm install
pnpm dev                      # → http://127.0.0.1:5173
pnpm type-check               # vue-tsc 类型检查
pnpm lint
pnpm build                    # 生产构建产物在 dist/
```

前端通过 `VITE_API_BASE_URL` 找后端；默认 `/api/v1` 走 Vite 代理到 `http://127.0.0.1:8000`。

---

## 3. 部署（轻量服务器 + Docker）

```bash
# 后端镜像（首次构建前需 cd backend && uv lock 生成 uv.lock）
docker build -f deploy/Dockerfile -t nianjia-api:local ./backend

# 本地一键起 backend + mysql
docker compose -f deploy/docker-compose.yml up -d

# 发布前必须单独跑迁移（不可依赖应用启动自动建表）
docker compose -f deploy/docker-compose.yml exec backend uv run alembic upgrade head
```

前端静态资源：`pnpm build` 产物上传 COS + CDN；单机形态可用 `deploy/nginx.conf` 托管并反代 `/api`。

---

## 4. 当前骨架范围与后续落地顺序

已就位：三端目录与可运行骨架、统一响应/异常/日志/配置/JWT 骨架、健康探针、迁移基座、部署文件。

按 `docs/05` 第 7 节推进：① 仓库骨架 + CI 两 Job 跑绿 → ② core + 登录接口 + 迁移打通 →
③ 主数据（门店 / SKU / 价目）→ ④ 主链路单据（要货 → 汇总 → 分拣 → 配送 → 签收 → 对账）→
⑤ 云上部署一次并踩熟发布回滚。
