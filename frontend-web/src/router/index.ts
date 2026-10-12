// 路由表 + 登录守卫骨架
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
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

// 登录守卫骨架：token 缺失跳登录页（登录页与鉴权接口接入后启用）
router.beforeEach((to, _from, next) => {
  const title = (to.meta?.title as string | undefined) ?? ''
  document.title = title ? title + ' - 念家鲜饺供应链' : '念家鲜饺供应链'
  // TODO(登录模块接入后): 无 token 且目标页非白名单 → next('/login')
  next()
})

export default router
