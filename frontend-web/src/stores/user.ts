// Pinia：用户会话骨架（登录接口接入后补全 action）
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { clearToken, setToken } from '@/api/request'

export type RoleCode = 'hq' | 'store' | 'driver'

export const useUserStore = defineStore('user', () => {
  const token = ref<string>('')
  const userId = ref<number | null>(null)
  const role = ref<RoleCode | ''>('')
  const storeId = ref<number | null>(null)

  /** 登录成功后写入会话（骨架：待 /auth/login 接入） */
  function login(payload: { token: string; userId: number; role: RoleCode; storeId?: number }) {
    token.value = payload.token
    userId.value = payload.userId
    role.value = payload.role
    storeId.value = payload.storeId ?? null
    setToken(payload.token)
  }

  function logout() {
    token.value = ''
    userId.value = null
    role.value = ''
    storeId.value = null
    clearToken()
  }

  return { token, userId, role, storeId, login, logout }
})
