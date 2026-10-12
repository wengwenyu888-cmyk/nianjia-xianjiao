<script setup lang="ts">
// 首页：骨架阶段用欢迎页确认三端与后端连通；展示当前登录用户与桌面客户端下载入口
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { health } from '@/api'
import mascotImg from '@/assets/mascot-green.png'
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
    <!-- 顶部毛玻璃导航条：品牌字 + 用户信息 + 退出 -->
    <header class="glass-nav top-nav">
      <div class="top-brand">念家鲜饺</div>
      <div class="top-user">
        <template v-if="userStore.isLoggedIn">
          <span class="user-name">{{ userStore.displayName }}</span>
          <el-tag
            v-for="code in userStore.roleCodes"
            :key="code"
            size="small"
            effect="plain"
            class="role-tag"
          >
            {{ roleText(code) }}
          </el-tag>
          <el-button link class="logout-btn" @click="handleLogout">退出登录</el-button>
        </template>
        <router-link v-else to="/login" class="login-link">去登录</router-link>
      </div>
    </header>

    <div class="home-main">
      <!-- Hero：白底大留白，大字标题 + 品牌承诺三连，图右文左 -->
      <section class="hero">
        <div class="hero-copy">
          <p class="eyebrow">念家鲜饺 · 供应链系统</p>
          <h1 class="hero-title">吃鲜饺，想念家</h1>
          <div class="promise-row">
            <span class="promise">馅不隔夜</span>
            <span class="promise">现包现煮</span>
            <span class="promise">伙伴幸福顾客幸福</span>
          </div>
          <p class="subtitle">门店要货 → 总部汇总 → 分拣 → 配送 → 签收 → 对账 一体化后台</p>
          <div class="status">
            <el-tag :type="apiStatus.includes('正常') ? 'success' : 'info'" effect="light">
              {{ apiStatus }}
            </el-tag>
            <span class="muted">API 基址：{{ apiBaseUrl }}</span>
          </div>
        </div>
        <div class="hero-mascot">
          <img :src="mascotImg" alt="念家鲜饺吉祥物" />
        </div>
      </section>

      <!-- 主数据导航：白卡片 + 极浅阴影，hover 上浮 2px + 主色描边 -->
      <section class="nav-section">
        <h2 class="section-title">主数据</h2>
        <div class="nav-cards">
          <router-link v-for="nav in masterNavs" :key="nav.to" :to="nav.to" class="nav-card">
            <span class="nav-card-title">{{ nav.title }}</span>
            <span class="nav-card-arrow" aria-hidden="true">→</span>
          </router-link>
        </div>
      </section>

      <!--
        桌面客户端下载入口：安装包由服务器 nginx 以 /downloads/ 静态目录托管，
        真实文件为 deploy/downloads/njxj-0.1.0-nianjia-xianjiao-desktop.exe（portable 免安装版）。
      -->
      <section class="download card">
        <div class="download-head">
          <h3>下载桌面客户端（Windows）</h3>
          <a href="/downloads/njxj-0.1.0-nianjia-xianjiao-desktop.exe" target="_blank" rel="noopener" class="download-link">
            <el-button type="primary" plain>下载桌面客户端（约 96MB）</el-button>
          </a>
        </div>
        <p class="muted">
          桌面客户端为同一份网页的 Electron 打包，功能与浏览器访问一致，安装包由服务器 nginx 提供下载。
        </p>
      </section>

      <!-- 业务入口卡片 -->
      <section class="feature-section">
        <div v-for="item in links" :key="item.title" class="feature-card card">
          <h3>{{ item.title }}</h3>
          <p class="muted">{{ item.desc }}</p>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.home {
  min-height: 100vh;
  background: var(--nf-cream);
}

/* ---- 顶部毛玻璃导航：.glass-nav 提供半透明与 backdrop-filter，这里管布局 ---- */
.top-nav {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  height: 64px;
  padding: 0 32px;
}
.top-brand {
  font-size: 20px;
  font-weight: 800;
  letter-spacing: 4px;
  color: var(--nf-deep);
}
.top-user {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 14px;
}
.user-name {
  font-weight: 600;
  color: var(--nf-ink);
}
/* 角色标签：嫩黄绿浅底 + 深绿字，克制点缀 */
.role-tag {
  --el-tag-bg-color: rgba(169, 217, 94, 0.18);
  --el-tag-border-color: rgba(62, 155, 71, 0.25);
  --el-tag-text-color: var(--nf-deep);
}
.logout-btn {
  color: #6b6b6b;
}
.login-link {
  color: var(--nf-green);
  text-decoration: none;
}
.login-link:hover {
  color: var(--nf-deep);
}

/* ---- 内容容器：居中 + 大留白 ---- */
.home-main {
  max-width: 1100px;
  margin: 0 auto;
  padding: 32px;
}

/* 通用白卡片：16px 圆角 + 柔和阴影，无描边 */
.card {
  background: #ffffff;
  border: 1px solid transparent;
  border-radius: 16px;
  box-shadow: var(--nf-shadow-card);
}

/* ---- Hero：白底大留白，图右文左 ---- */
.hero {
  display: flex;
  align-items: center;
  gap: 56px;
  padding: 56px;
  border-radius: 24px;
  background: #ffffff;
  box-shadow: var(--nf-shadow-card);
}
.hero-copy {
  flex: 1 1 auto;
  min-width: 0;
}
.eyebrow {
  margin: 0 0 14px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 2px;
  color: var(--nf-green);
}
/* 大标题：40px+ 最粗档（docs/07 §3 大字号层级） */
.hero-title {
  margin: 0 0 22px;
  font-size: 46px;
  line-height: 1.15;
  font-weight: 800;
  letter-spacing: 2px;
  color: var(--nf-ink);
}
.promise-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 22px;
}
/* 品牌承诺三连：嫩黄绿浅底小标签 */
.promise {
  font-size: 13px;
  line-height: 1;
  padding: 8px 14px;
  border-radius: 999px;
  color: var(--nf-deep);
  background: rgba(169, 217, 94, 0.18);
  border: 1px solid rgba(62, 155, 71, 0.18);
}
.subtitle {
  margin: 0 0 22px;
  font-size: 15px;
  color: #6b6b6b;
}
.status {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.muted {
  color: var(--nf-muted);
  font-size: 13px;
  margin: 0;
}
/* 吉祥物：图片底色即深绿 #2A7A38，用同色圆角容器承载，成为一组色块视觉 */
.hero-mascot {
  flex: 0 0 auto;
  width: 280px;
  border-radius: 24px;
  overflow: hidden;
  background: var(--nf-deep);
  box-shadow: 0 12px 32px rgba(42, 122, 56, 0.18);
}
.hero-mascot img {
  display: block;
  width: 100%;
  height: auto;
}

/* ---- 主数据导航卡片 ---- */
.nav-section {
  margin-top: 56px;
}
.section-title {
  margin: 0 0 20px;
  font-size: 24px;
  font-weight: 700;
  color: var(--nf-ink);
}
.nav-cards {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 20px;
}
.nav-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 26px 24px;
  background: #ffffff;
  border: 1px solid transparent;
  border-radius: 16px;
  box-shadow: var(--nf-shadow-card);
  color: var(--nf-ink);
  text-decoration: none;
  transition: transform 0.2s ease, border-color 0.2s, box-shadow 0.2s;
}
.nav-card:hover {
  transform: translateY(-2px);
  border-color: var(--nf-green);
  box-shadow: var(--nf-shadow-card-hover);
  text-decoration: none;
}
.nav-card-title {
  font-size: 20px;
  font-weight: 700;
}
.nav-card-arrow {
  color: var(--nf-green);
  font-size: 18px;
}

/* ---- 下载卡片 ---- */
.download {
  margin-top: 56px;
  padding: 28px 32px;
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
  font-size: 20px;
  font-weight: 700;
  color: var(--nf-ink);
}
.download-link {
  text-decoration: none;
}
.download .muted {
  margin-top: 10px;
}

/* ---- 业务入口卡片：同款白卡片 + hover 上浮 ---- */
.feature-section {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 20px;
  margin-top: 56px;
}
.feature-card {
  padding: 26px 24px;
  transition: transform 0.2s ease, border-color 0.2s, box-shadow 0.2s;
}
.feature-card:hover {
  transform: translateY(-2px);
  border-color: var(--nf-green);
  box-shadow: var(--nf-shadow-card-hover);
}
.feature-card h3 {
  margin: 0 0 10px;
  font-size: 20px;
  font-weight: 700;
  color: var(--nf-ink);
}
.feature-card .muted {
  line-height: 1.6;
}

@media (max-width: 900px) {
  .hero {
    flex-direction: column;
    align-items: flex-start;
    gap: 32px;
    padding: 32px;
  }
  .hero-title {
    font-size: 34px;
  }
  .hero-mascot {
    width: 200px;
  }
  .nav-cards,
  .feature-section {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .nav-section,
  .download,
  .feature-section {
    margin-top: 40px;
  }
}
@media (max-width: 560px) {
  .home-main {
    padding: 20px;
  }
  .top-nav {
    padding: 0 20px;
  }
  .nav-cards,
  .feature-section {
    grid-template-columns: 1fr;
  }
}
</style>
