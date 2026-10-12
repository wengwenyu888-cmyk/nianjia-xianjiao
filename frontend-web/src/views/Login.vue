<script setup lang="ts">
// 登录页：视觉对齐 prototype/00-login.html（淡色渐变背景 + 居中卡片）
// 提交流程：本地校验 -> store.login() 调 /auth/login -> token 写 localStorage -> 跳转首页
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import mascotImg from '@/assets/mascot-green.png'
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
  <!-- V3：Apple 式双栏。左栏品牌视觉（深绿渐变 + 吉祥物），右栏奶油白表单 -->
  <div class="login-page">
    <aside class="brand-pane">
      <div class="mascot-frame">
        <img class="mascot" :src="mascotImg" alt="念家鲜饺吉祥物" />
      </div>
      <div class="brand-copy">
        <div class="brand-name">念家鲜饺</div>
        <p class="brand-slogan">吃鲜饺，想念家</p>
      </div>
    </aside>

    <main class="form-pane">
      <div class="form-card">
        <h1 class="title">欢迎回来</h1>
        <p class="subtitle">登录念家鲜饺供应链系统</p>

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
    </main>
  </div>
</template>

<style scoped>
/* 页面：左右双栏，占满整屏，无滚动 */
.login-page {
  display: flex;
  min-height: 100vh;
}

/* ---- 左栏（桌面 55%）：深绿渐变 + 居中的吉祥物与品牌字 ----
 * 深绿渐变：品牌绿 #3E9B47 → 深绿 #2A7A38（docs/07 V3 色板）。 */
.brand-pane {
  flex: 0 0 55%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 32px;
  padding: 48px 40px;
  background: linear-gradient(150deg, #3E9B47 0%, #2A7A38 100%);
  overflow: hidden;
}
/* 吉祥物承载框：底色取图片实测底色 #2A7A38，图片与框无缝贴合，只保留大圆角 */
.mascot-frame {
  display: flex;
  max-height: 60vh;
  max-width: 100%;
  border-radius: 24px;
  overflow: hidden;
  background: #2A7A38;
  box-shadow: 0 18px 40px rgba(0, 0, 0, 0.18);
}
.mascot {
  display: block;
  max-height: 60vh;
  max-width: 100%;
  width: auto;
}
.brand-copy {
  text-align: center;
}
.brand-name {
  font-size: 32px;
  font-weight: 800;
  letter-spacing: 6px;
  color: #ffffff;
}
.brand-slogan {
  margin: 10px 0 0;
  font-size: 15px;
  letter-spacing: 3px;
  color: rgba(255, 255, 255, 0.78);
}

/* ---- 右栏（45%）：奶油白底 + 居中表单卡片 ---- */
.form-pane {
  flex: 1 1 45%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 32px;
  background: var(--nf-cream);
}
.form-card {
  box-sizing: border-box;
  width: 100%;
  max-width: 380px;
  padding: 40px 36px 28px;
  border-radius: 20px;
  background: #ffffff;
  box-shadow: var(--nf-shadow-card);
  /* 极简输入框：无边框，底色灰白，聚焦时品牌绿描边 */
  --el-input-bg-color: #f5f1e8;
  --el-input-border-color: transparent;
  --el-input-hover-border-color: transparent;
  --el-input-focus-border-color: var(--nf-green);
  --el-input-text-color: var(--nf-ink);
  --el-input-placeholder-color: #a8a8a8;
}
.title {
  margin: 0 0 10px;
  font-size: 32px;
  font-weight: 800;
  letter-spacing: 1px;
  color: var(--nf-ink);
}
.subtitle {
  margin: 0 0 28px;
  font-size: 14px;
  color: #6b6b6b;
}
.login-form :deep(.el-form-item__label) {
  font-size: 13px;
  font-weight: 500;
  color: #6b6b6b;
  padding-bottom: 6px;
}
.login-form :deep(.el-form-item) {
  margin-bottom: 18px;
}
.login-form :deep(.el-input__wrapper) {
  padding: 4px 14px;
  border-radius: 10px;
}
.login-form :deep(.el-input__wrapper.is-focus) {
  background: #ffffff;
}
.submit {
  width: 100%;
  height: 46px;
  margin-top: 6px;
  border-radius: 10px;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 4px;
}
.copy {
  margin-top: 22px;
  text-align: center;
  font-size: 12px;
  color: #a8a8a8;
}

/* ---- 窄屏（<768px）：隐藏左栏，只留表单 ---- */
@media (max-width: 767px) {
  .brand-pane {
    display: none;
  }
  .form-pane {
    flex: 1 1 100%;
    padding: 32px 20px;
  }
  .form-card {
    padding: 32px 24px 24px;
    box-shadow: none;
    background: transparent;
  }
}
</style>
