# desktop —— 念家鲜饺 Windows 桌面壳

## 这是什么

用 Electron 把线上网页包成 Windows 桌面客户端，业务代码为零，只多一个主进程入口和一个最小预加载脚本：

- `main.js`：创建 1200x800 窗口；**生产模式加载服务器上的网页地址**（同源，接口正常）；站外链接转系统浏览器。
- `preload.js`：最小桥接，只暴露 Electron / Chrome / Node 版本号。
- 安全默认：`contextIsolation: true`、`nodeIntegration: false`、`sandbox: true`。

网页端仍是响应式网页，浏览器直接访问照常可用；桌面壳只是多一种承载方式。
API 是端无关 REST：壳与网页共用同一套接口，未来加小程序 / 安卓 / iOS 客户端不受影响。

## ⚠️ 为什么加载远程地址而不是本地 dist（重要历史坑）

桌面壳最初用 `file://` 加载打包进来的本地网页（`resources/frontend-web/index.html`）。
这会导致**接口全部失败**，登录页报「网络异常，请求失败」——原因：

前端接口用相对路径 `/api/v1/...`，在 `file://` 协议下会被解析成 `file:///api/v1/...`，
请求根本没发到服务器（nginx 访问日志里查无此请求，可佐证）。

**现在的做法**：生产模式加载远程地址 `http://180.76.248.14`（与网页端同源，接口直接可用），
本地 dist 仅作「网络不通时的离线兜底」——离线时能看到界面并弹提示，但接口不可用。

额外收益：前端发版后桌面端**无需重新下载安装包**，打开即是最新版。

## dev 跑法

```bash
# 终端 1：先起网页开发服务器
cd frontend-web && pnpm install && pnpm dev        # http://127.0.0.1:5173

# 终端 2：起桌面壳
cd desktop && pnpm install && pnpm dev             # 加载 http://127.0.0.1:5173
```

`pnpm dev` 等价于 `electron . --dev`。也可用环境变量：`$env:DESKTOP_DEV='1'; pnpm start`。

## 打包（electron-builder）

```bash
cd frontend-web && pnpm build     # 生成 frontend-web/dist（仅作离线兜底，也建议同步）
cd ../desktop && pnpm dist        # 打 Windows nsis 安装包
# 免安装单文件版（当前线上分发的就是这个）：
cd desktop && pnpm exec electron-builder --win portable
```

- 产物目录：`desktop/release/`（portable 版文件名 `njxj-<version>-<name>.exe`）。
- 应用图标：`desktop/build/icon.ico`（由品牌吉祥物图生成，多尺寸 16→256）。
- `extraResources` 会把 `../frontend-web/dist` 复制进包内，作为离线兜底。

## 换加载地址（DESKTOP_URL 优先）

`main.js` 的加载顺序：

1. `DESKTOP_URL` 环境变量（最高优先，可指到测试/预发/正式任意环境）
2. `DESKTOP_DEV=1` 或 `--dev` → `http://127.0.0.1:5173`
3. 其余 → 生产地址常量 `PROD_URL`（默认 `http://180.76.248.14`）

```powershell
$env:DESKTOP_URL='https://app.example.com'; pnpm start     # 壳加载指定环境网页
```

> 注意：`DESKTOP_URL` 与 `PROD_URL` 的源（origin）都会加入「站内白名单」，
> 否则页面内路由跳转会被误判为站外而弹出系统浏览器。

## 说明

- 依赖只有 `electron` 与 `electron-builder`，无其它运行时依赖。
- `node_modules/`、`dist/`、`release/` 已在 `.gitignore` 中忽略。
- 安装包未做代码签名：Windows SmartScreen 首次运行会提示「未知发布者」，
  点「更多信息 → 仍要运行」即可；正式对外分发建议购买代码签名证书。
