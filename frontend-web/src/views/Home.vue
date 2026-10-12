<script setup lang="ts">
// 首页：骨架阶段用欢迎页确认三端与后端连通
import { onMounted, ref } from 'vue'

import { health } from '@/api'

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

onMounted(async () => {
  try {
    const res = await health()
    apiStatus.value = res.status === 'ok' ? '后端连接正常' : '后端状态异常'
  } catch {
    apiStatus.value = '后端未连通（请确认 uvicorn 已启动）'
  }
})
</script>

<template>
  <div class="home">
    <el-card shadow="never" class="banner">
      <h1>念家鲜饺供应链</h1>
      <p class="subtitle">门店要货 → 总部汇总 → 分拣 → 配送 → 签收 → 对账 一体化后台</p>
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
.grid {
  margin-top: 16px;
}
.grid h3 {
  margin: 0 0 8px;
  font-size: 16px;
}
</style>
