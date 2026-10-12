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
  <div class="login-page">
    <div class="login-card">
      <div class="logo">念家鲜饺</div>
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
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  box-sizing: border-box;
  /* 与原型 body.nf-auth 一致的淡色渐变背景 */
  background: linear-gradient(150deg, #fdeceb 0%, #f5f7fa 45%, #eaf1f8 100%);
}
.login-card {
  width: 100%;
  max-width: 400px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 10px 30px rgba(31, 45, 61, 0.12);
  padding: 32px 28px 24px;
  text-align: center;
}
.logo {
  font-size: 26px;
  font-weight: 700;
  color: #c0392b;
  letter-spacing: 4px;
}
.sub {
  font-size: 12px;
  color: #909399;
  margin-top: 6px;
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
