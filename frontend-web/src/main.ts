// 应用入口：装配 Pinia、路由、Element Plus 与全局样式
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from '@/App.vue'
import router from '@/router'

import 'element-plus/dist/index.css'
// V2 品牌主题：覆盖 Element Plus CSS 变量（色板依据 docs/07-品牌与设计规范.md）
import '@/styles/theme.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)
// 中后台默认中文
app.use(ElementPlus, { locale: zhCn })

app.mount('#app')
