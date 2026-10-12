// 念家鲜饺供应链系统 —— 桌面壳最小预加载脚本
// 只暴露「只读版本号」，不做任何业务桥接；contextIsolation 安全默认见 main.js
const { contextBridge } = require('electron')

contextBridge.exposeInMainWorld('desktop', {
  // 单一用途：在控制台/关于页确认用户装的是哪个壳版本，便于排查问题
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
    node: process.versions.node
  }
})
