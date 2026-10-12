// 按业务模块聚合接口（骨架阶段只放模块文件出口，避免各页面直接 import axios）
import service, { request } from '@/api/request'

export { request, service }

// 主数据模块接口出口（§8.2 主数据端点：门店 / SKU / 供应商 / 价目表）
export * from './store'

/** 健康检查：用于本地联调时确认后端连通 */
export function health(): Promise<{ status: string; app: string; version: string }> {
  return request({ url: '/health', method: 'get' })
}
