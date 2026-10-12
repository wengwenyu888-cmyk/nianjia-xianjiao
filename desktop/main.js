// 念家鲜饺供应链系统 —— Windows 桌面壳（Electron 主进程）
// 定位：只做「开一个窗口加载现成网页」，不写业务代码；网页本体在 frontend-web/。
const { app, BrowserWindow, shell } = require('electron')
const path = require('node:path')

// 开发服务器地址（frontend-web 的 vite dev server）
const DEV_URL = 'http://127.0.0.1:5173'

// 开发模式判定：DESKTOP_DEV=1，或命令行 --dev
// （npm run dev 用 --dev，跨平台且不必额外装 cross-env；两种方式等价）
const isDev = process.env.DESKTOP_DEV === '1' || process.argv.includes('--dev')

// 加载地址优先级：DESKTOP_URL（想指到任意环境时用，最高优先）> 开发服务器 > 构建产物
function resolveTarget() {
  if (process.env.DESKTOP_URL) {
    return { kind: 'url', value: process.env.DESKTOP_URL }
  }
  if (isDev) {
    return { kind: 'url', value: DEV_URL }
  }
  // 生产：加载 frontend-web/dist/index.html（file:// 本地文件协议）
  // 未打包时取仓库里的 ../frontend-web/dist；打包后由 electron-builder 的
  // extraResources 复制到 resources/frontend-web/，故两种位置都要认。
  const file = app.isPackaged
    ? path.join(process.resourcesPath, 'frontend-web', 'index.html')
    : path.join(__dirname, '..', 'frontend-web', 'dist', 'index.html')
  return { kind: 'file', value: file }
}

// 站内地址判定：本地文件、开发服务器、以及 DESKTOP_URL 指定的源
function isInternal(url) {
  try {
    const target = new URL(url)
    if (target.protocol === 'file:') return true
    const allowed = new Set([new URL(DEV_URL).origin])
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

  const target = resolveTarget()
  if (target.kind === 'url') {
    win.loadURL(target.value)
  } else {
    win.loadFile(target.value)
  }

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
