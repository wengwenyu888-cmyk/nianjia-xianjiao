// 路由表 + 登录守卫
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { getToken } from '@/api/request'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login.vue'),
    meta: { title: '登录' }
  },
  {
    path: '/',
    name: 'home',
    component: () => import('@/views/Home.vue'),
    meta: { title: '首页' }
  },
  // ---- 主数据管理（§8.2 主数据端点）----
  {
    path: '/stores',
    name: 'store-list',
    component: () => import('@/views/StoreList.vue'),
    meta: { title: '门店管理' }
  },
  {
    path: '/skus',
    name: 'sku-list',
    component: () => import('@/views/SkuList.vue'),
    meta: { title: 'SKU 管理' }
  },
  {
    path: '/suppliers',
    name: 'supplier-list',
    component: () => import('@/views/SupplierList.vue'),
    meta: { title: '供应商管理' }
  },
  {
    path: '/prices',
    name: 'price-list',
    component: () => import('@/views/PriceList.vue'),
    meta: { title: '价目表' }
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFound.vue'),
    meta: { title: '页面不存在' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 全局前置守卫：无 token 只能进 /login；有 token 访问 /login 直接回首页
router.beforeEach((to) => {
  const title = (to.meta?.title as string | undefined) ?? ''
  document.title = title ? title + ' - 念家鲜饺供应链' : '念家鲜饺供应链'

  const token = getToken()
  if (token && to.path === '/login') {
    return { path: '/' }
  }
  if (!token && to.path !== '/login') {
    // 带上来源地址，登录成功后由 Login.vue 回跳
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  return true
})

export default router
