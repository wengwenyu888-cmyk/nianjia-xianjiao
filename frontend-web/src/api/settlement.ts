// 对账核算 API（docs/02 §8.2「对账核算」端点，路径与方法逐字对齐）
// 统一响应 { code, message, data } 由 request.ts 解包；分页形状 { list, total, page, page_size } 见 §8.1。
import { request } from '@/api/request'
import type { PageQuery, PageResult } from '@/api/store'

/**
 * 生成 Idempotency-Key（§8.1 幂等：写接口可带该请求头，≤64 字符）。
 * reconcile 表有 idempotency_key 列（uk_idem）：定时任务重跑与手工重试须复用同一个键。
 */
export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return 'njxj-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10)
}

/** 对账单状态（§7.5 reconcile.status）：draft 待确认 / confirmed 已确认 / done 已归档 */
export type ReconcileStatus = 'draft' | 'confirmed' | 'done'

/**
 * 对账单（§7.5 reconcile，门店×周期）。
 * 注意：表内只有 total_amount（本周期内部结算额）与 diff_amount（与管家婆差异额）两个金额列，
 * 页面展示的「应配金额」= total_amount、「实收金额」= total_amount - diff_amount。
 */
export interface Reconcile {
  id: number
  /** 对账周期，形如 2026-W42（ISO 周） */
  period: string
  store_id: number
  /** 本周期内部结算额（元） */
  total_amount: number
  /** 与外部台账（管家婆）差异额 */
  diff_amount: number
  status: ReconcileStatus
  confirmed_by?: number | null
  confirmed_at?: string | null
  created_at?: string | null
  /** 展示用：后端返回则优先使用，未返回时页面按门店映射表补齐 */
  store_name?: string | null
}

/** 生成对账单入参（POST /reconciles/generate）：store_id 省略表示按周期生成全部门店 */
export interface ReconcileGeneratePayload {
  period: string
  store_id?: number
}

/** 对账查询参数（§8.2 GET /reconciles?period=&store_id=） */
export interface ReconcileQuery extends PageQuery {
  period?: string
  store_id?: number
}

/** 确认对账入参（POST /reconciles/{id}/confirm）：记录与管家婆的差异额 */
export interface ReconcileConfirmPayload {
  diff_amount: number
}

/**
 * 门店盈亏核算（GET /stores/{id}/profit?period=）。
 * docs/02 §8.2 只约定端点与用途，未固定响应字段名，这里按 §7.5/§01 业务口径命名，
 * 页面侧对字段名做了别名容错（见 ReconcilePage 的 readNum）。
 */
export interface StoreProfit {
  store_id: number
  store_name?: string | null
  period: string
  /** 营业额（元）：门店周期内销售流水合计 */
  revenue: number
  /** 配货成本（元）：本周期对账单 total_amount 汇总（内部调拨价） */
  dispatch_amount: number
  /** 报损金额（元）：本期报损数量×当时价 */
  loss_amount?: number
  /** 毛利（元）= 营业额 - 配货成本 - 报损金额 */
  gross_profit: number
  /** 毛利率（%），后端未给时页面按 毛利/营业额 计算 */
  gross_margin?: number
}

/**
 * 门店 KPI（GET /stores/{id}/kpi?period=）。
 * 语义依据 docs/02 §8.2「KPI(损耗率/要货准确率/周转)」与 docs/01 业务手册指标定义；
 * 响应字段名同样以后端为准，页面侧做了别名容错。
 */
export interface StoreKpi {
  store_id: number
  store_name?: string | null
  period: string
  /** 营业额（元） */
  revenue: number
  /** 毛利（元） */
  gross_profit: number
  /** 损耗率（%）= 报损量 ÷ 入库量 */
  loss_rate: number
  /** 要货准确率（%）：要货量与实际销量的匹配程度 */
  order_accuracy: number
  /** 库存周转天数：周期内平均库存 ÷ 日均销量 */
  turnover_days: number
}

/** POST /reconciles/generate 按周期生成对账单（幂等：重跑复用同一个 key） */
export function generateReconcile(
  data: ReconcileGeneratePayload,
  idempotencyKey: string = newIdempotencyKey()
): Promise<PageResult<Reconcile> | Reconcile[]> {
  return request<PageResult<Reconcile> | Reconcile[]>({
    url: '/reconciles/generate',
    method: 'post',
    data,
    headers: { 'Idempotency-Key': idempotencyKey }
  })
}

/** GET /reconciles?period=&store_id= 查对账（分页形状归一，兼容后端直接返回数组） */
export async function listReconciles(
  params: ReconcileQuery = {}
): Promise<PageResult<Reconcile>> {
  const data = await request<PageResult<Reconcile> | Reconcile[]>({
    url: '/reconciles',
    method: 'get',
    params
  })
  if (Array.isArray(data)) {
    return {
      list: data,
      total: data.length,
      page: params.page ?? 1,
      page_size: params.page_size ?? data.length
    }
  }
  return data
}

/**
 * POST /reconciles/{id}/confirm 确认（记录与管家婆差异）。
 * 确认是状态流转（draft→confirmed），由后端状态机兜底，不带幂等键。
 */
export function confirmReconcile(
  id: number,
  data: ReconcileConfirmPayload
): Promise<Reconcile> {
  return request<Reconcile>({ url: '/reconciles/' + id + '/confirm', method: 'post', data })
}

/** GET /stores/{id}/profit?period= 门店盈亏核算 */
export function getStoreProfit(storeId: number, period: string): Promise<StoreProfit> {
  return request<StoreProfit>({
    url: '/stores/' + storeId + '/profit',
    method: 'get',
    params: { period }
  })
}

/** GET /stores/{id}/kpi?period= KPI（损耗率/要货准确率/周转） */
export function getStoreKpi(storeId: number, period: string): Promise<StoreKpi> {
  return request<StoreKpi>({
    url: '/stores/' + storeId + '/kpi',
    method: 'get',
    params: { period }
  })
}
