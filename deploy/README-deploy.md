# 念家鲜饺供应链系统 · 生产部署手册

> 目标机型：百度云 BCC / Ubuntu 22.04 / **2 vCPU · 1.3GB 内存 · 40GB 磁盘**
> 部署形态：单机 Docker Compose（MySQL 8.4 + 后端 + nginx 同机）
> 代码仓库：https://github.com/wengwenyu888-cmyk/nianjia-xianjiao （公有仓库）
> 预计耗时：首次 40~70 分钟（含 2GB swap、前端构建与后端镜像构建）

## 0. 前置与约定

- **内存预算**：mysql 400m + backend 400m + nginx 100m ≈ 900m；宿主机其余进程约占 250~350m。**必须先做步骤 2 的 2GB swap**，否则首次建库/构建镜像的瞬时峰值会触发 OOM Killer。
- **磁盘**：40GB 足够，但仍配置 Docker 日志轮转（步骤 6）与 7 天备份保留（步骤 13）。
- **路径约定**：仓库克隆到 `/opt/nianjia-xianjiao`，下文命令以此为基准；换路径请整体替换。
- **占位符写法**：`<...>` 表示需要替换成实际值；`$USER` 为当前登录用户。
- **安全底线**：`deploy/.env` 含全部口令，权限设为 600，绝不提交仓库、绝不贴进对话或工单。
- 需要服务器能访问 github.com（步骤 7 有镜像/代理替代方案）与容器镜像仓库。

## 步骤 1：系统更新与基础工具

~~~bash
sudo apt update && sudo apt -y upgrade
sudo apt -y install ca-certificates curl gnupg git ufw fail2ban
~~~

## 步骤 2：创建 2GB swap（1.3GB 内存的必要项）

~~~bash
# 物理内存只有 1.3GB，构建镜像/首次建库会瞬时超限，swap 是防 OOM 的底线
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
# 写入 fstab，保证重启后自动挂载
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
# 降低换出倾向：有 swap 兜底，但尽量不提前换出（避免拖慢数据库）
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-nianjia.conf
echo 'vm.vfs_cache_pressure=50' | sudo tee -a /etc/sysctl.d/99-nianjia.conf
sudo sysctl --system
# 验证：Swap 行应显示 2.0Gi
free -h
~~~

## 步骤 3：设置时区

~~~bash
# 业务口径为北京时间（对账日切、配送时效），需与 deploy/.env 的 TZ 一致
sudo timedatectl set-timezone Asia/Shanghai
timedatectl
~~~

## 步骤 4：fail2ban（sshd jail）

~~~bash
# 公网 22 端口必被爆破，fail2ban 是成本最低的缓解手段
sudo tee /etc/fail2ban/jail.local >/dev/null <<'EOF'
[DEFAULT]
bantime  = 1h
findtime = 10m
maxretry = 5
backend  = systemd

[sshd]
enabled = true
port    = 22
EOF
sudo systemctl enable --now fail2ban
# 验证：Status 应显示 enabled 与当前封禁列表
sudo fail2ban-client status sshd
~~~

## 步骤 5：安装 Docker 与 compose 插件（官方 apt 源）

~~~bash
# 用官方源，不用发行版自带的旧版 docker.io
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
# 生成 apt 源
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt update
sudo apt -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
# 当前用户免 sudo 用 docker（重新登录后生效；单人运维服务器可接受）
sudo usermod -aG docker $USER
# 重新登录后验证
docker --version && docker compose version
~~~

## 步骤 6：Docker 日志轮转（防磁盘写满）

~~~bash
# 40GB 磁盘 + 容器长期运行：不限制日志会悄悄吃满磁盘
# 国内网络拉不动镜像时，可在同一 JSON 里加 "registry-mirrors": ["https://<镜像加速地址>"]
sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
EOF
sudo systemctl restart docker
docker info | grep -A2 'Logging Driver'
~~~

## 步骤 7：拉取代码（GitHub 公有仓库）

~~~bash
sudo mkdir -p /opt && sudo chown $USER:$USER /opt
cd /opt
git clone https://github.com/wengwenyu888-cmyk/nianjia-xianjiao.git
cd /opt/nianjia-xianjiao
git log -1 --oneline
~~~

服务器访问不了 github.com 时（先验证：`curl -I https://github.com`）：

~~~bash
# 方案 A：走 HTTP 代理（<proxy-host>:<port> 换成实际代理）
git -c http.proxy=http://<proxy-host>:<port> -c https.proxy=http://<proxy-host>:<port> \
  clone https://github.com/wengwenyu888-cmyk/nianjia-xianjiao.git
# 方案 B：国内 GitHub 加速前缀（第三方服务，稳定性自担；<mirror> 换成可用前缀）
git clone https://<mirror>/https://github.com/wengwenyu888-cmyk/nianjia-xianjiao.git
# 方案 C：本机打包上传（最稳）
#   本机执行：git archive -o nianjia.tar.gz HEAD
#   上传后：  scp nianjia.tar.gz user@<服务器IP>:/opt/ && tar -xzf nianjia.tar.gz
~~~

## 步骤 8：生成后端锁文件 backend/uv.lock（构建硬前置）

**当前仓库未提交 `backend/uv.lock`，而 `deploy/Dockerfile` 会执行 COPY pyproject.toml uv.lock 与 `uv sync --frozen`——缺锁文件时镜像构建会直接在 COPY 处失败。上线前必须在服务器补出该文件：**

~~~bash
cd /opt/nianjia-xianjiao/backend
# 方案 A：服务器安装 uv 后生成
#   curl -LsSf https://astral.sh/uv/install.sh | sh && source $HOME/.local/bin/env
#   uv lock
# 方案 B：用官方 uv 镜像生成（无需本机安装 uv）
docker run --rm -v "$PWD:/app" -w /app ghcr.io/astral-sh/uv:latest uv lock
ls -l uv.lock
~~~

> 长期做法：把 `backend/uv.lock` 提交进仓库，保证 CI、本地、线上三方依赖一致（docs/05 已将其列为基线）。

## 步骤 9：构建前端 frontend-web/dist

~~~bash
# 9.1 安装 Node 20 + pnpm（服务器无 Node 时）
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt -y install nodejs
sudo corepack enable
corepack prepare pnpm@9 --activate
node -v && pnpm -v

# 9.2 构建
cd /opt/nianjia-xianjiao/frontend-web
pnpm config set registry https://registry.npmmirror.com   # 国内加速，可选
pnpm install
# 生产接口基址：nginx 已反代 /api，保持相对路径即可
cp .env.example .env.production
pnpm build
ls -lh dist/        # 应看到 index.html 与 assets/
~~~

> 仓库当前未提交 `pnpm-lock.yaml`，因此用 `pnpm install`，不要用 `--frozen-lockfile`；建议尽快补提交锁文件。

**替代方案：服务器不装 Node，用 Docker 构建前端（产物同样写回宿主 dist）**

~~~bash
cd /opt/nianjia-xianjiao
docker run --rm -v "$PWD/frontend-web:/app" -w /app node:20-alpine sh -c \
  "corepack enable && corepack prepare pnpm@9 --activate && pnpm config set registry https://registry.npmmirror.com && pnpm install && pnpm build"
ls -lh frontend-web/dist/
~~~

## 步骤 10：配置生产变量 deploy/.env

~~~bash
cd /opt/nianjia-xianjiao
cp deploy/.env.example deploy/.env
chmod 600 deploy/.env
# 生成密钥材料（每条各生成一次，分别填入 .env）
openssl rand -base64 24    # -> MYSQL_ROOT_PASSWORD
openssl rand -base64 24    # -> DB_PASSWORD
openssl rand -hex 32       # -> JWT_SECRET_KEY（必须 >= 32 字节）
nano deploy/.env
~~~

`deploy/.env` 必填清单：

| 变量 | 填写值 | 说明 |
| --- | --- | --- |
| `MYSQL_ROOT_PASSWORD` | 随机串 | 数据库 root 口令，仅容器内与备份脚本使用 |
| `MYSQL_DATABASE` | `nianjia_xianjiao` | 业务库名，同时作为后端 DB_NAME |
| `DB_USER` / `DB_PASSWORD` | `nianjia` / 随机串 | 后端专用账号（非 root） |
| `JWT_SECRET_KEY` | 32 字节以上随机串 | 长度不足后端会拒绝启动 |
| `CORS_ORIGINS` | `https://<域名>` | 只填真实访问来源，禁止写 `*` |
| `ENV` | `prod` | 生产必须 prod（自动关闭 /docs） |
| `VITE_API_BASE_URL` | `/api/v1` | 前端构建期变量（写入步骤 9 的 .env.production） |
| `TZ` | `Asia/Shanghai` | MySQL / 后端 / 备份脚本共用 |

> compose 会自动读取与编排文件同目录的 `deploy/.env`；若你的 compose 版本未自动加载，可在命令后追加 `--env-file deploy/.env`。

## 步骤 11：启动整个栈

~~~bash
cd /opt/nianjia-xianjiao
# --build 保证镜像与当前代码一致；后端容器启动时会自动执行 alembic upgrade head 建表
docker compose -f deploy/docker-compose.prod.yml up -d --build
docker compose -f deploy/docker-compose.prod.yml ps
# 首次建库较慢，等 healthcheck 变 healthy；跟随后端日志直到出现「应用启动」
docker compose -f deploy/docker-compose.prod.yml logs -f backend
~~~

若不想把迁移放进启动命令，也可手动执行一次性迁移：

~~~bash
docker compose -f deploy/docker-compose.prod.yml run --rm backend alembic upgrade head
~~~

## 步骤 12：验证清单

### 12.1 后端健康

~~~bash
curl -i http://127.0.0.1/health                   # 应 200，body 含 "status":"ok"
curl -s http://127.0.0.1/api/v1/health/readiness  # 应 database: up
~~~

### 12.2 数据库 26 张业务表

~~~bash
# 密码经 MYSQL_PWD 传入，避免出现在 ps 命令行与 shell 历史
export MYSQL_PWD="$(grep -E '^MYSQL_ROOT_PASSWORD=' deploy/.env | cut -d= -f2-)"

# 期望 27 = 26 张业务表 + alembic_version
docker compose -f deploy/docker-compose.prod.yml exec -T mysql \
  mysql -uroot -e "SELECT COUNT(*) AS tables_total FROM information_schema.tables WHERE table_schema='nianjia_xianjiao';"

# 列出表名人工核对
docker compose -f deploy/docker-compose.prod.yml exec -T mysql \
  mysql -uroot -e "SHOW TABLES FROM nianjia_xianjiao;"

unset MYSQL_PWD
~~~

### 12.3 浏览器与静态资源

- 浏览器打开 `http://<服务器公网IP>/`（或已解析的域名）：应看到首页/登录页，F12 无资源 404。
- 刷新任意前端路由（如 `/orders`）仍返回页面，说明 SPA 回退生效。

### 12.4 端口暴露面

~~~bash
# 只应看到 22 / 80（443 待证书方案）；不应出现 3306 / 8000
sudo ss -tlnp
~~~

## 步骤 13：挂载每日备份（crontab）

~~~bash
chmod +x /opt/nianjia-xianjiao/deploy/backup.sh
# 先手动跑一次确认可用（会写 /var/log/mysql-backup.log）
sudo /opt/nianjia-xianjiao/deploy/backup.sh
sudo tail -n 20 /var/log/mysql-backup.log
ls -lh /var/backups/mysql/
# 挂每日 03:00（避开白天业务高峰）
( sudo crontab -l 2>/dev/null; echo '0 3 * * * /opt/nianjia-xianjiao/deploy/backup.sh' ) | sudo crontab -
sudo crontab -l
~~~

> 备份本地保留 7 天（由 `RETENTION_DAYS` 控制），日志写 `/var/log/mysql-backup.log`；失败会写 ALERT 行，配置 `ALERT_WEBHOOK` 可推送企业微信/钉钉。

## 步骤 14：安全清单（上线前逐项打勾）

- [ ] `ufw` 只放行 22/80/443，其余拒绝：
  `sudo ufw allow 22/tcp && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw enable && sudo ufw status numbered`
- [ ] MySQL **不映射公网端口**：`docker compose ... ps` 中 mysql 无 ports；`ss -tlnp` 无 3306
- [ ] 后端 **不映射公网端口**：仅 `expose 8000`，公网只能经 nginx 的 `/api` 进入
- [ ] `deploy/.env` 权限 600、未入库：`git status` 不应出现 .env
- [ ] 口令与 JWT 密钥均为上线时新生成的随机值，**与开发/测试环境不同**
- [ ] **定期改密码提醒**：建议每 90 天轮换 `MYSQL_ROOT_PASSWORD`、`DB_PASSWORD`、`JWT_SECRET_KEY`；改后执行 `docker compose -f deploy/docker-compose.prod.yml up -d` 重建。JWT 轮换会使全部登录态失效，请在低峰执行
- [ ] 后续 HTTPS：申请证书后增加 443 监听与 80 跳转；`/health` 已预留直通供负载均衡/监控使用
- [ ] 备份**异地留存**：本机 7 天之外，定期把 `/var/backups/mysql` 同步到对象存储（COS/BOS）
- [ ] 服务器 root 登录与密码登录按需收紧（改用密钥登录）

## 附：常用运维命令

~~~bash
cd /opt/nianjia-xianjiao
C="docker compose -f deploy/docker-compose.prod.yml"

$C ps                          # 查看状态
$C logs -f backend             # 后端日志
$C logs --tail=100 nginx       # nginx 日志
$C restart backend             # 只重启后端
$C down                        # 停栈（不动命名卷，数据保留）
$C up -d --build               # 更新发版
docker system prune -f         # 清理无用镜像/构建缓存（磁盘紧张时）
du -sh /var/lib/docker /var/backups/mysql
~~~

**更新发版流程**

~~~bash
cd /opt/nianjia-xianjiao
git pull
cd frontend-web && pnpm install && pnpm build && cd ..
docker compose -f deploy/docker-compose.prod.yml up -d --build
docker compose -f deploy/docker-compose.prod.yml logs -f backend
~~~

**回滚**

镜像按代码重建：`git checkout <上一个可用 commit>` 后重复上面的发版命令。数据库迁移只前进不回滚，回滚代码前先确认旧版本兼容已迁移的表结构。

## 附：故障速查

| 现象 | 排查方向 |
| --- | --- |
| 构建在 COPY uv.lock 处失败 | 步骤 8 未执行，backend/uv.lock 缺失 |
| backend 反复重启 | `docker compose ... logs backend`；多为 DB_PASSWORD/DB_NAME 不匹配或 JWT_SECRET_KEY < 32 字节 |
| mysql 一直 unhealthy | 内存不足被 OOM；确认 swap 已启用，`dmesg -T | tail` 看 OOM 记录 |
| 打开 80 空白 / 404 | frontend-web/dist 未构建或为空（步骤 9） |
| /api 502 | backend 未就绪；`docker compose ... ps` 看 backend 状态与日志 |
