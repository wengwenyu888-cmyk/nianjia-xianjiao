// 桌面壳冒烟测试：隐藏窗口加载生产地址，实测接口能否调通
// 用法：pnpm exec electron _smoke.js
// 结果写入 _smoke-result.txt（Windows 上 Electron 的 stdout 不回传控制台，故落盘）
const { app, BrowserWindow } = require('electron')
const fs = require('node:fs')
const path = require('node:path')

const PROD_URL = process.env.DESKTOP_URL || 'http://180.76.248.14'
const OUT = path.join(__dirname, '_smoke-result.txt')
const lines = []
const log = (s) => { lines.push(s) }

// 超时保护：15 秒内没跑完就强制落盘退出（沙箱/代理环境下 loadURL 可能挂起）
setTimeout(() => {
  try { fs.writeFileSync(OUT, lines.join('\n') + '\nTIMEOUT_15S\n', 'utf8') } catch {}
  app.exit(0)
}, 15000)

app.whenReady().then(async () => {
  const win = new BrowserWindow({
    show: false,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true }
  })
  try {
    await win.loadURL(PROD_URL + '/login')
    log('PAGE_LOADED=' + PROD_URL)
    const health = await win.webContents.executeJavaScript(
      "fetch('/api/v1/health',{cache:'no-store'}).then(r=>r.json()).then(j=>JSON.stringify(j)).catch(e=>'ERR:'+e.message)"
    )
    log('HEALTH=' + health)
    const login = await win.webContents.executeJavaScript(
      "fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'Admin@12345'})}).then(r=>r.json()).then(j=>'code='+j.code+' token='+(j.data&&j.data.token?'YES':'NO')+' user='+(j.data&&j.data.user?j.data.user.username:'-')).catch(e=>'ERR:'+e.message)"
    )
    log('LOGIN=' + login)
  } catch (e) {
    log('FAIL=' + e.message)
  } finally {
    try { fs.writeFileSync(OUT, lines.join('\n') + '\n', 'utf8') } catch {}
    app.exit(0)
  }
})
