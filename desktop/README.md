# desktop —— 念家鲜饺 Windows 桌面壳

## 这是什么

用 Electron 把 `frontend-web/` 里**同一份 Vue 网页**包成 Windows 桌面客户端，
业务代码为零，只多一个主进程入口和一个最小预加载脚本：

- `main.js`：创建 1200x800 窗口；按模式加载开发服务器或构建产物；站外链接转系统浏览器。
- `preload.js`：最小桥接，只暴露 Electron / Chrome / Node 版本号。
- 安全默认：`contextIsolation: true`、`nodeIntegration: false`、`sandbox: true`。

网页端仍然是响应式网页，浏览器直接访问照常可用；桌面壳只是多一种承载方式。
API 是端无关 REST：壳与网页共用同一套接口，未来加小程序 / 安卓 / iOS 客户端不受影响。

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
cd frontend-web && pnpm build     # 先生成 frontend-web/dist
cd ../desktop && pnpm dist        # 打 Windows nsis 安装包 → desktop/release/
```

- 产物：`desktop/release/` 下的 nsis 安装包（.exe）。
- 打包时由 electron-builder 的 `extraResources` 把 `../frontend-web/dist` 复制进安装包，
  壳启动后用 `file://` 加载 `resources/frontend-web/index.html`。
- **前置要求**：`file://` 下不能用绝对根路径，构建时必须让资源走相对路径
  （Vite 的 `base: './'`，即在 `frontend-web/vite.config.ts` 里设置 `base`）。
  当前 `vite.config.ts` 未设置 `base`，打桌面包前需要补上；不改会白屏，
  浏览器 `pnpm dev` 不受影响。

## 换加载地址（DESKTOP_URL 优先）

`main.js` 的加载顺序：

1. `DESKTOP_URL`（最高优先，可指到任意网页地址；同时决定哪些跳转算「站内」）
2. `DESKTOP_DEV=1` 或 `--dev` → `http://127.0.0.1:5173`
3. 其余 → `frontend-web/dist/index.html`（本地文件协议）

```powershell
$env:DESKTOP_URL='https://app.example.com'; pnpm start     # 壳加载线上网页
```

## 说明

- 依赖只有 `electron` 与 `electron-builder`，无其它运行时依赖。
- `node_modules/`、`dist/`、`release/` 已在 `.gitignore` 中忽略。
