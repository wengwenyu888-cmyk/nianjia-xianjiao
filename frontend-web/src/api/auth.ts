// 认证 API（后端契约：统一响应 { code, message, data }，由 request.ts 解包）
// POST /api/v1/auth/login -> data: { token, token_type, user }
import { request } from '@/api/request'

/** 登录返回的用户信息（与后端 data.user 字段一致） */
export interface UserInfo {
  id: number
  username: string
  display_name: string
  store_id: number | null
  role_codes: string[]
  permission_codes: string[]
}

/** 登录响应 data */
export interface LoginResult {
  token: string
  token_type: string
  user: UserInfo
}

/**
 * 账号密码登录。
 * 成功由调用方（stores/user.ts）负责把 token 写入 localStorage。
 */
export function login(username: string, password: string): Promise<LoginResult> {
  return request<LoginResult>({
    url: '/auth/login',
    method: 'post',
    data: { username, password }
  })
}

/**
 * 获取当前登录用户（刷新页面后补全用户信息 / 校验 token 有效性）。
 * 约定路径 GET /auth/me；后端鉴权接口落地后如有出入以实际为准。
 */
export function fetchMe(): Promise<UserInfo> {
  return request<UserInfo>({ url: '/auth/me', method: 'get' })
}
