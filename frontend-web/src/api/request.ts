// axios 封装：统一响应拦截、JWT 注入、错误提示
import axios, { type AxiosInstance, type AxiosRequestConfig, type AxiosResponse } from 'axios'
import { ElMessage } from 'element-plus'

/** 后端统一响应体（与 backend/app/schema/common.py 的 ApiResponse 对齐） */
export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T | null
}

const TOKEN_KEY = 'njxj_access_token'

/** 读取 access token（登录模块接入后改由 pinia store 管理） */
export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? ''
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

const service: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' }
})

// 请求拦截：注入 JWT
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

// 响应拦截：统一处理 HTTP 错误与业务错误码
service.interceptors.response.use(
  (response: AxiosResponse) => response,
  (error) => {
    const status = error?.response?.status
    if (status === 401) {
      clearToken()
      ElMessage.error('登录已过期，请重新登录')
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
 */
export async function request<T = unknown>(config: AxiosRequestConfig): Promise<T> {
  const response = await service.request<ApiResponse<T>>(config)
  const body = response.data
  if (body && typeof body === 'object' && 'code' in body) {
    if (body.code !== 0) {
      ElMessage.error(body.message || '请求失败')
      throw new Error(body.message || 'business error')
    }
    return body.data as T
  }
  return body as unknown as T
}

export default service
