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
    <!-- 品牌 banner：深蓝渐变底 + slogan「吃鲜饺，想念家」+ 品牌承诺三连 -->
    <el-card shadow="never" class="banner">
      <div class="banner-head">
        <div class="banner-brand">
          <p class="brand-line">念家鲜饺 · 供应链系统</p>
          <h1>吃鲜饺，想念家</h1>
          <div class="promise-row">
            <span class="promise">馅不隔夜</span>
            <span class="promise">现包现煮</span>
            <span class="promise">伙伴幸福顾客幸福</span>
          </div>
          <p class="subtitle">门店要货 → 总部汇总 → 分拣 → 配送 → 签收 → 对账 一体化后台</p>
        </div>
        <div class="user-box">
          <template v-if="userStore.isLoggedIn">
            <span class="user-name">{{ userStore.displayName }}</span>
            <el-tag
              v-for="code in userStore.roleCodes"
              :key="code"
              size="small"
              type="info"
              effect="plain"
              class="role-tag"
            >
              {{ roleText(code) }}
            </el-tag>
            <el-button link type="primary" class="logout-btn" @click="handleLogout">
              退出登录
            </el-button>
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

    <!-- 主数据导航：12px 圆角白卡片，hover 主色描边 -->
    <el-card shadow="never" class="nav">
      <span class="nav-label">主数据：</span>
      <router-link v-for="nav in masterNavs" :key="nav.to" :to="nav.to" class="nav-link">
        {{ nav.title }}
      </router-link>
    </el-card>

    <!--
      桌面客户端下载入口：安装包由服务器 nginx 以 /downloads/ 静态目录托管，
      真实文件为 deploy/downloads/njxj-0.1.0-nianjia-xianjiao-desktop.exe（portable 免安装版）。
    -->
    <el-card shadow="never" class="download">
      <div class="download-head">
        <h3>下载桌面客户端（Windows）</h3>
        <a href="/downloads/njxj-0.1.0-nianjia-xianjiao-desktop.exe" target="_blank" rel="noopener" class="download-link">
          <el-button type="primary" plain>下载桌面客户端（约 96MB）</el-button>
        </a>
      </div>
      <p class="muted">
        桌面客户端为同一份网页的 Electron 打包，功能与浏览器访问一致，安装包由服务器 nginx 提供下载。
      </p>
    </el-card>

    <el-row :gutter="16" class="grid">
      <el-col v-for="item in links" :key="item.title" :xs="24" :sm="12" :md="6">
        <el-card shadow="hover" class="feature-card">
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

/* ---- 品牌 banner：深蓝 ink → 天蓝 对角渐变 ---- */
.banner {
  --el-card-bg-color: transparent;
  background: linear-gradient(135deg, #0e346b 0%, #0f92d2 100%);
  border: none;
  border-radius: 12px;
  overflow: hidden;
}
.banner-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.brand-line {
  margin: 0;
  font-size: 13px;
  letter-spacing: 2px;
  color: rgba(255, 255, 255, 0.82);
}
.banner h1 {
  margin: 8px 0 12px;
  font-size: 30px;
  font-weight: 700;
  letter-spacing: 3px;
  color: #ffffff;
}
.promise-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
/* 品牌承诺三连：白描边小标签 */
.promise {
  font-size: 12px;
  line-height: 1;
  padding: 5px 12px;
  border-radius: 999px;
  color: #ffffff;
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.32);
}
.user-box {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 14px;
  /* 深色 banner 上的链接按钮配色：通过 Element 变量继承，不改业务逻辑 */
  --el-button-text-color: #d8ecff;
  --el-button-hover-text-color: #ffffff;
  --el-button-hover-link-text-color: #ffffff;
}
.user-name {
  font-weight: 600;
  color: #ffffff;
}
/* 角色标签：深蓝底上的半透明白标签 */
.role-tag {
  --el-tag-bg-color: rgba(255, 255, 255, 0.16);
  --el-tag-border-color: rgba(255, 255, 255, 0.4);
  --el-tag-text-color: #ffffff;
}
.login-link {
  color: #d8ecff;
  text-decoration: none;
}
.login-link:hover {
  color: #ffffff;
}
.subtitle {
  color: rgba(255, 255, 255, 0.78);
  margin: 0;
  font-size: 13px;
}
.status {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
}
/* 辅助文字：蓝灰；banner 内另用半透明白 */
.muted {
  color: #707c9d;
  font-size: 13px;
}
.status .muted {
  color: rgba(255, 255, 255, 0.72);
}

/* ---- 主数据导航卡片 ---- */
.nav {
  margin-top: 16px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}
.nav-label {
  color: #0e346b;
  font-size: 14px;
  font-weight: 600;
}
.nav-link {
  color: #0e346b;
  text-decoration: none;
  padding: 8px 18px;
  border: 1px solid #d0e5f6;
  border-radius: 12px;
  background: #ffffff;
  transition: color 0.2s, border-color 0.2s, background-color 0.2s;
}
.nav-link:hover {
  color: #157fd1;
  border-color: #157fd1;
  background: #e8f2fa;
  text-decoration: none;
}

/* ---- 下载卡片 ---- */
.download {
  margin-top: 16px;
  border-radius: 12px;
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
  color: #0e346b;
}
.download-link {
  text-decoration: none;
}
.download p {
  margin: 8px 0 0;
}

/* ---- 业务入口卡片：12px 圆角 + hover 主色描边 ---- */
.grid {
  margin-top: 16px;
}
.grid :deep(.el-card) {
  border-radius: 12px;
  height: 100%;
  transition: border-color 0.2s;
}
.grid :deep(.el-card:hover) {
  border-color: #157fd1;
}
.grid h3 {
  margin: 0 0 8px;
  font-size: 16px;
  color: #0e346b;
}
</style>
