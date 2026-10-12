<script setup lang="ts">
// 首页：骨架阶段用欢迎页确认三端与后端连通；展示当前登录用户与桌面客户端下载入口
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { health } from '@/api'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()

const apiStatus = ref('检测中…')
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'

const links = [
  { title: '要货汇总', desc: '按门店/商品维度汇总当日要货量' },
  { title: '分拣管理', desc: '生成分拣单并记录实际分拣数量' },
  { title: '配送调度', desc: '派车派单，司机端查看配送任务' },
  { title: '签收对账', desc: '电子签收、差异上报与门店盈亏对账' }
]

/** 主数据管理入口，与 router 中 /stores、/skus、/suppliers、/prices 一一对应 */
const masterNavs = [
  { to: '/stores', title: '门店管理' },
  { to: '/skus', title: 'SKU 管理' },
  { to: '/suppliers', title: '供应商管理' },
  { to: '/prices', title: '价目表' }
]

/** 角色码 -> 中文标签；未知角色码原样展示，避免后端新增角色时前端显示空白 */
const ROLE_LABELS: Record<string, string> = {
  admin: '管理员',
  ops: '运营',
  hq: '总部',
  store: '门店',
  store_manager: '店长',
  driver: '司机'
}

function roleText(code: string): string {
  return ROLE_LABELS[code] ?? code
}

/** 退出登录：清 store + localStorage 后回登录页 */
async function handleLogout(): Promise<void> {
  userStore.logout()
  await router.push('/login')
}

onMounted(async () => {
  try {
    const res = await health()
    apiStatus.value = res.status === 'ok' ? '后端连接正常' : '后端状态异常'
  } catch {
    apiStatus.value = '后端未连通（请确认 uvicorn 已启动）'
  }

  // 有 token 但本地无用户信息（例如换了浏览器标签或缓存被清）时补拉一次
  if (userStore.isLoggedIn && !userStore.user) {
    try {
      await userStore.fetchMe()
    } catch {
      // token 失效时 request.ts 已清 token 并跳登录页
    }
  }
})
</script>

<template>
  <div class="home">
    <el-card shadow="never" class="banner">
      <div class="banner-head">
        <div>
          <h1>念家鲜饺供应链</h1>
          <p class="subtitle">门店要货 → 总部汇总 → 分拣 → 配送 → 签收 → 对账 一体化后台</p>
        </div>
        <div class="user-box">
          <template v-if="userStore.isLoggedIn">
            <span class="user-name">{{ userStore.displayName }}</span>
            <el-tag
              v-for="code in userStore.roleCodes"
              :key="code"
              size="small"
              type="danger"
              effect="light"
            >
              {{ roleText(code) }}
            </el-tag>
            <el-button link type="primary" @click="handleLogout">退出登录</el-button>
          </template>
          <router-link v-else to="/login" class="login-link">去登录</router-link>
        </div>
      </div>
      <div class="status">
        <el-tag :type="apiStatus.includes('正常') ? 'success' : 'info'" effect="light">
          {{ apiStatus }}
        </el-tag>
        <span class="muted">API 基址：{{ apiBaseUrl }}</span>
      </div>
    </el-card>

    <el-card shadow="never" class="nav">
      <span class="nav-label">主数据：</span>
      <router-link v-for="nav in masterNavs" :key="nav.to" :to="nav.to" class="nav-link">
        {{ nav.title }}
      </router-link>
    </el-card>

    <!--
      桌面客户端下载入口。
      /downloads/ 为占位路径：安装包由服务器 nginx 以静态目录托管
      （见 deploy/nginx.conf），正式发布后替换为真实文件名，
      例如 /downloads/njxj-setup-v1.0.0.exe。
    -->
    <el-card shadow="never" class="download">
      <div class="download-head">
        <h3>下载桌面客户端（Windows）</h3>
        <a href="/downloads/" target="_blank" rel="noopener" class="download-link">
          <el-button type="primary" plain>前往下载页</el-button>
        </a>
      </div>
      <p class="muted">
        桌面客户端为同一份网页的 Electron 打包，功能与浏览器访问一致，安装包由服务器 nginx 提供下载。
      </p>
    </el-card>

    <el-row :gutter="16" class="grid">
      <el-col v-for="item in links" :key="item.title" :xs="24" :sm="12" :md="6">
        <el-card shadow="hover">
          <h3>{{ item.title }}</h3>
          <p class="muted">{{ item.desc }}</p>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.home {
  padding: 24px;
}
.banner h1 {
  margin: 0 0 8px;
  font-size: 24px;
}
.banner-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.user-box {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 14px;
}
.user-name {
  font-weight: 600;
  color: #303133;
}
.login-link {
  color: #409eff;
  text-decoration: none;
}
.subtitle {
  color: #606266;
  margin: 0 0 16px;
}
.status {
  display: flex;
  align-items: center;
  gap: 12px;
}
.muted {
  color: #909399;
  font-size: 13px;
}
.nav {
  margin-top: 16px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
}
.nav-label {
  color: #606266;
  font-size: 14px;
}
.nav-link {
  color: #409eff;
  text-decoration: none;
}
.nav-link:hover {
  text-decoration: underline;
}
.download {
  margin-top: 16px;
}
.download-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.download-head h3 {
  margin: 0;
  font-size: 16px;
}
.download-link {
  text-decoration: none;
}
.download p {
  margin: 8px 0 0;
}
.grid {
  margin-top: 16px;
}
.grid h3 {
  margin: 0 0 8px;
  font-size: 16px;
}
</style>
