// 念家鲜饺供应链系统 —— Windows 桌面壳（Electron 主进程）
// 定位：只做「开一个窗口加载现成网页」，不写业务代码；网页本体在 frontend-web/。
const { app, BrowserWindow, dialog, shell } = require('electron')
const path = require('node:path')

// 开发服务器地址（frontend-web 的 vite dev server）
const DEV_URL = 'http://127.0.0.1:5173'

// 生产环境网页地址（服务端部署地址）。
// 为什么加载远程而不是本地 dist：前端接口用的是相对路径 /api/v1，
// 若以 file:// 加载本地 dist，相对路径会被解析成 file:///api/v1/... 而永远失败
// （表现为「网络异常，请求失败」）。加载远程地址即与网页端同源，接口正常，
// 且前端发版后桌面端无需重新下载安装包。
// 需要指向其它环境时用环境变量 DESKTOP_URL 覆盖。
const PROD_URL = process.env.DESKTOP_URL || 'http://180.76.248.14'

// 开发模式判定：DESKTOP_DEV=1，或命令行 --dev
// （npm run dev 用 --dev，跨平台且不必额外装 cross-env；两种方式等价）
const isDev = process.env.DESKTOP_DEV === '1' || process.argv.includes('--dev')

// 本地构建产物路径（仅作网络不可用时的离线兜底；离线界面只能看，接口不可用）
// 未打包时取仓库里的 ../frontend-web/dist；打包后由 electron-builder 的
// extraResources 复制到 resources/frontend-web/，故两种位置都要认。
function localDistFile() {
  return app.isPackaged
    ? path.join(process.resourcesPath, 'frontend-web', 'index.html')
    : path.join(__dirname, '..', 'frontend-web', 'dist', 'index.html')
}

// 加载地址优先级：DESKTOP_URL（指到任意环境时用，最高优先）> 开发服务器 > 生产远程地址
function resolveTarget() {
  if (process.env.DESKTOP_URL) {
    return { kind: 'url', value: process.env.DESKTOP_URL }
  }
  if (isDev) {
    return { kind: 'url', value: DEV_URL }
  }
  return { kind: 'url', value: PROD_URL }
}

// 站内地址判定：本地文件、开发服务器、以及 DESKTOP_URL 指定的源
function isInternal(url) {
  try {
    const target = new URL(url)
    if (target.protocol === 'file:') return true
    // 站内白名单：开发服务器 + 生产地址（+ 自定义 DESKTOP_URL）
    // 必须含生产地址，否则加载远程页面后，页面内路由跳转会被误判为站外而转系统浏览器
    const allowed = new Set([new URL(DEV_URL).origin, new URL(PROD_URL).origin])
    if (process.env.DESKTOP_URL) allowed.add(new URL(process.env.DESKTOP_URL).origin)
    return allowed.has(target.origin)
  } catch {
    return false
  }
}

// 站外链接统一交给系统默认浏览器，避免在壳里开出「没有地址栏的浏览器窗口」
function openExternal(url) {
  if (/^https?:\/\//i.test(url)) {
    shell.openExternal(url).catch(() => {})
  }
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 960,
    minHeight: 640,
    title: '念家鲜饺供应链系统',
    autoHideMenuBar: true, // 桌面壳不需要菜单栏，窗口更干净
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true, // 渲染进程与预加载上下文隔离（安全默认）
      nodeIntegration: false, // 网页里拿不到 Node API
      sandbox: true // 保持 Electron 默认沙箱，进一步收窄渲染进程能力
    }
  })

  // 页面里 window.open / target=_blank：不开新窗口，直接转系统浏览器
  win.webContents.setWindowOpenHandler(({ url }) => {
    openExternal(url)
    return { action: 'deny' }
  })

  // 页面跳转：站外地址拦下转系统浏览器，站内路由（前端 hash/history）正常放行
  win.webContents.on('will-navigate', (event, url) => {
    if (!isInternal(url)) {
      event.preventDefault()
      openExternal(url)
    }
  })

  // 加载：优先进程解析出的地址；远程不可达时回退本地 dist（离线可看界面，接口不可用）
  const target = resolveTarget()
  win.loadURL(target.value).catch(() => {
    const fallback = localDistFile()
    win.loadFile(fallback).catch(() => {})
    dialog.showMessageBox(win, {
      type: 'warning',
      title: '网络不可用',
      message: '无法连接服务器，已切换到离线界面。',
      detail: `请检查网络后重启应用。服务器地址：${PROD_URL}`,
      buttons: ['知道了']
    }).catch(() => {})
  })

  return win
}

app.whenReady().then(() => {
  createWindow()

  // macOS 习惯：点 Dock 图标且无窗口时重建窗口（Windows 上无实际影响）
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

// 关掉所有窗口即退出（Windows 桌面壳的常规行为）
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
