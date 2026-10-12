// axios 封装：统一响应拦截、JWT 注入、错误提示
import axios, { type AxiosInstance, type AxiosRequestConfig, type AxiosResponse } from 'axios'
import { ElMessage } from 'element-plus'

/** 后端统一响应体（与 backend/app/schema/common.py 的 ApiResponse 对齐） */
export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T | null
}

/** token 持久化键名：本项目方案只存 localStorage，不使用 cookie */
export const TOKEN_KEY = 'njxj_token'

/** 未认证业务码（与后端 40100 对齐） */
const UNAUTHORIZED_CODE = 40100

/** 登录页路径：未认证时跳转过去 */
const LOGIN_PATH = '/login'

/** 读取 access token（登录后由 stores/user.ts 写入） */
export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? ''
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

/** 是否登录接口本身：登录失败返回 40100 时不能再跳 /login，否则死循环 */
function isLoginRequest(config?: AxiosRequestConfig): boolean {
  return (config?.url ?? '').includes('/auth/login')
}

/** 跳转登录页：用 location 而非 import router，避免 request 与 router 的循环依赖 */
function redirectToLogin(): void {
  if (typeof window === 'undefined') return
  if (window.location.pathname !== LOGIN_PATH) {
    window.location.href = LOGIN_PATH
  }
}

/** 未认证统一处理：清 token + 跳登录页；登录接口自身除外 */
function handleUnauthorized(config?: AxiosRequestConfig): void {
  if (isLoginRequest(config)) return
  clearToken()
  ElMessage.error('登录已过期，请重新登录')
  redirectToLogin()
}

const service: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' }
})

// 请求拦截：附带 Authorization: Bearer <token>
service.interceptors.request.use(
  (config) => {
    const token = getToken()
    if (token) {
      config.headers.Authorization = 'Bearer ' + token
    }
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截：统一处理 HTTP 错误（业务码 40100 在 request() 内处理）
service.interceptors.response.use(
  (response: AxiosResponse) => response,
  (error) => {
    const status = error?.response?.status
    if (status === 401) {
      // 登录接口的 401 是账号密码错误，不触发跳转
      handleUnauthorized(error?.config)
      if (isLoginRequest(error?.config)) {
        ElMessage.error(error?.response?.data?.message || '账号或密码错误')
      }
    } else if (status === 403) {
      ElMessage.error('没有访问权限')
    } else if (status === 429) {
      ElMessage.error('操作过于频繁，请稍后再试')
    } else if (status && status >= 500) {
      ElMessage.error('服务异常，请稍后重试')
    } else if (error?.code === 'ECONNABORTED') {
      ElMessage.error('请求超时，请检查网络')
    } else {
      ElMessage.error(error?.response?.data?.message || '网络异常，请求失败')
    }
    return Promise.reject(error)
  }
)

/**
 * 统一请求方法：拆掉一层 { code, message, data } 包装，直接返回 data。
 * code !== 0 视为业务失败，弹提示并抛错，调用方无需重复判断。
 * code 40100 额外清 token 并跳登录页（登录接口自身除外）。
 */
export async function request<T = unknown>(config: AxiosRequestConfig): Promise<T> {
  const response = await service.request<ApiResponse<T>>(config)
  const body = response.data
  if (body && typeof body === 'object' && 'code' in body) {
    if (body.code !== 0) {
      if (body.code === UNAUTHORIZED_CODE) {
        handleUnauthorized(config)
        if (isLoginRequest(config)) {
          ElMessage.error(body.message || '账号或密码错误')
        }
        throw new Error(body.message || 'unauthorized')
      }
      ElMessage.error(body.message || '请求失败')
      throw new Error(body.message || 'business error')
    }
    return body.data as T
  }
  return body as unknown as T
}

export default service
