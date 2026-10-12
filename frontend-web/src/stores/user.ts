// Pinia 用户会话：登录 / 登出 / 拉取当前用户，token 与用户信息持久化到 localStorage
import { defineStore } from 'pinia'

import { fetchMe as fetchMeApi, login as loginApi, type UserInfo } from '@/api/auth'
import { clearToken, getToken, setToken } from '@/api/request'

/** 用户信息持久化键名：token 单独存 njxj_token，用户信息存这里 */
const USER_KEY = 'njxj_user'

/** 读本地缓存的用户信息；JSON 损坏时按未登录处理，不让页面崩 */
function readStoredUser(): UserInfo | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as UserInfo) : null
  } catch {
    return null
  }
}

/** 写入/清除本地用户信息缓存（null 表示清除） */
function writeStoredUser(user: UserInfo | null): void {
  if (user) {
    localStorage.setItem(USER_KEY, JSON.stringify(user))
  } else {
    localStorage.removeItem(USER_KEY)
  }
}

export const useUserStore = defineStore('user', {
  // state：token 与当前用户，初值从 localStorage 恢复（刷新页面不丢登录态）
  state: () => ({
    token: getToken(),
    user: readStoredUser() as UserInfo | null
  }),

  // getters：登录判定与常用派生字段
  getters: {
    isLoggedIn: (state): boolean => !!state.token,
    displayName: (state): string => state.user?.display_name || state.user?.username || '',
    roleCodes: (state): string[] => state.user?.role_codes ?? [],
    permissionCodes: (state): string[] => state.user?.permission_codes ?? []
  },

  // actions：登录 / 登出 / 拉取当前用户
  actions: {
    /** 登录：调接口成功后写 store 并持久化 token + 用户信息 */
    async login(username: string, password: string): Promise<UserInfo> {
      const res = await loginApi(username, password)
      this.token = res.token
      this.user = res.user
      setToken(res.token)
      writeStoredUser(res.user)
      return res.user
    },

    /** 登出：清空内存态与 localStorage */
    logout(): void {
      this.token = ''
      this.user = null
      clearToken()
      writeStoredUser(null)
    },

    /** 拉取当前用户：用于刷新后补全信息或校验 token 是否仍有效 */
    async fetchMe(): Promise<UserInfo> {
      const user = await fetchMeApi()
      this.user = user
      writeStoredUser(user)
      return user
    }
  }
})
