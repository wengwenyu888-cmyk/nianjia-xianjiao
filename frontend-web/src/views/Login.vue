<script setup lang="ts">
// 登录页：视觉对齐 prototype/00-login.html（淡色渐变背景 + 居中卡片）
// 提交流程：本地校验 -> store.login() 调 /auth/login -> token 写 localStorage -> 跳转首页
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const form = reactive({ username: '', password: '' })
const loading = ref(false)

/** 登录提交 */
async function handleLogin(): Promise<void> {
  if (!form.username.trim()) {
    ElMessage.warning('请输入账号')
    return
  }
  if (!form.password) {
    ElMessage.warning('请输入密码')
    return
  }

  loading.value = true
  try {
    await userStore.login(form.username.trim(), form.password)
    ElMessage.success('登录成功')
    // 支持来源页回跳：/login?redirect=/stores
    const redirect = route.query.redirect
    const target = typeof redirect === 'string' && redirect ? redirect : '/'
    await router.replace(target)
  } catch {
    // 账号密码错误 / 网络异常等提示已由 request.ts 统一弹出，这里不重复提示
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <!-- V2：蓝渐变背景 + 居中白卡片 + 饺子 logo + 品牌 slogan -->
  <div class="login-page">
    <div class="login-card">
      <!-- 饺子 logo：内联 SVG，两段圆弧拼出月牙饺身，金黄 #f5a623 勾出褶边（不引外部图片） -->
      <div class="logo-mark" aria-hidden="true">
        <svg viewBox="0 0 64 64" width="64" height="64" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <linearGradient id="nfDumpling" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stop-color="#0f92d2" />
              <stop offset="100%" stop-color="#0e346b" />
            </linearGradient>
          </defs>
          <!-- 饺身：上弧 + 下弧两段圆弧闭合 -->
          <path d="M6 38 A26 26 0 0 1 58 38 A34 9 0 0 0 6 38 Z" fill="url(#nfDumpling)" />
          <!-- 褶边：金黄弧线点缀 -->
          <path
            d="M13 33 Q32 20 51 33"
            stroke="#f5a623"
            stroke-width="2.5"
            stroke-linecap="round"
            fill="none"
          />
          <circle cx="32" cy="22" r="2.2" fill="#f5a623" />
        </svg>
      </div>

      <div class="brand">念家鲜饺</div>
      <div class="slogan">吃鲜饺，想念家</div>
      <div class="promise">馅不隔夜 · 现包现煮</div>
      <div class="sub">供应链系统 · 总部统采统配平台</div>

      <el-form class="login-form" :model="form" label-position="top" @submit.prevent="handleLogin">
        <el-form-item label="账号">
          <el-input
            v-model="form.username"
            size="large"
            placeholder="请输入工号 / 手机号"
            autocomplete="username"
            clearable
          />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            size="large"
            placeholder="请输入密码"
            autocomplete="current-password"
            show-password
            @keyup.enter="handleLogin"
          />
        </el-form-item>
      </el-form>

      <el-button class="submit" type="primary" size="large" :loading="loading" @click="handleLogin">
        登 录
      </el-button>

      <div class="copy">© 2026 念家鲜饺 供应链系统</div>
    </div>
  </div>
</template>

<style scoped>
/* 页面：天蓝 → 深蓝 对角渐变（docs/07：蓝 = 信赖与品质） */
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  box-sizing: border-box;
  background: linear-gradient(135deg, #0f92d2 0%, #0e346b 100%);
}
/* 居中白卡片：12px 圆角 + 柔和阴影 */
.login-card {
  width: 100%;
  max-width: 400px;
  background: #ffffff;
  border-radius: 12px;
  box-shadow: 0 18px 44px rgba(14, 52, 107, 0.28);
  padding: 32px 28px 24px;
  text-align: center;
}
.logo-mark {
  display: flex;
  justify-content: center;
  margin-bottom: 8px;
}
/* 品牌名：深蓝 ink，加粗 + 字距 */
.brand {
  font-size: 26px;
  font-weight: 700;
  color: #0e346b;
  letter-spacing: 4px;
}
/* slogan：主色 */
.slogan {
  font-size: 15px;
  font-weight: 600;
  color: #157fd1;
  letter-spacing: 2px;
  margin-top: 8px;
}
/* 品牌承诺行：蓝灰辅助文字 */
.promise {
  font-size: 12px;
  color: #707c9d;
  letter-spacing: 1px;
  margin-top: 6px;
}
.sub {
  font-size: 12px;
  color: #7f97bc;
  margin-top: 10px;
}
.login-form {
  margin-top: 24px;
  text-align: left;
}
.submit {
  width: 100%;
}
.copy {
  font-size: 12px;
  color: #a8abb2;
  margin-top: 20px;
}
</style>
