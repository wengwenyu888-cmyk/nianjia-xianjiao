// 配送签收 / 报损 API（docs/02 §8.2「配送签收」「报损」端点，路径与方法逐字对齐）
// 统一响应 { code, message, data } 由 request.ts 解包；分页形状 { list, total, page, page_size } 见 §8.1。
import { request } from '@/api/request'
import type { PageQuery, PageResult } from '@/api/store'

/**
 * 生成 Idempotency-Key（§8.1 幂等：写接口可带该请求头，≤64 字符）。
 * 同一次业务提交的重试必须复用同一个键，因此调用方可以先生成、失败重试时原样传入。
 */
export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return 'njxj-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10)
}

/** 配送单状态机（§7.4 delivery.status）：loaded→on_way→signed/partial/rejected */
export type DeliveryStatus = 'loaded' | 'on_way' | 'signed' | 'partial' | 'rejected'

/** 签收单状态（§7.4 sign.status） */
export type SignStatus = 'full' | 'partial' | 'reject'

/** 报损类型（§7.5 loss.type）：临期 / 破损 / 盘点差异 */
export type LossType = 'expire' | 'damage' | 'count_diff'

/** 报损状态（§7.5 loss.status）：draft 待审 / approved 已审 */
export type LossStatus = 'draft' | 'approved'

/** 配送明细（§7.4 delivery_item；qty_base = 发送数量，基础单位） */
export interface DeliveryItem {
  id?: number
  delivery_id?: number
  /** 来源分拣明细，用于单据链追溯（配送明细→分拣明细→要货单明细） */
  pick_item_id?: number | null
  sku_id: number
  batch_no: string
  qty_base: number
  /** 展示用：后端若返回品名则优先使用，未返回时页面按 SKU 映射表补齐 */
  sku_name?: string | null
}

/** 配送单（§7.4 delivery：一车一店一单） */
export interface Delivery {
  id: number
  delivery_no: string
  summary_id: number
  store_id: number
  /** DATE 格式 YYYY-MM-DD（§8.1 时间约定） */
  require_date: string
  driver_id?: number | null
  plate_no?: string | null
  status: DeliveryStatus
  loaded_at?: string | null
  signed_at?: string | null
  created_at?: string | null
  /** 明细：仅详情接口 GET /deliveries/{id} 返回 */
  items?: DeliveryItem[]
  /** 以下为可选展示字段：后端返回则优先使用，未返回时由前端映射/按需展开明细补齐 */
  store_name?: string | null
  driver_name?: string | null
  sign_id?: number | null
  item_count?: number | null
  qty_total?: number | null
}

/** 装车明细入参（POST /deliveries 的 items 项） */
export interface DeliveryItemPayload {
  pick_item_id?: number | null
  sku_id: number
  batch_no: string
  qty_base: number
}

/** 生成配送单（装车）入参：summary_id 在 §7.4 中为非空列，故必填 */
export interface DeliveryCreatePayload {
  summary_id: number
  store_id: number
  require_date: string
  driver_id?: number | null
  plate_no?: string | null
  items: DeliveryItemPayload[]
}

/** 配送单列表查询参数（§8.2 仅定义 driver_id / require_date；page/page_size 为 §8.1 通用分页） */
export interface DeliveryQuery extends PageQuery {
  driver_id?: number
  require_date?: string
}

/** 签收明细入参：只送实收数量；应送数量由后端按配送明细回填（§7.4 sign_item.send_qty_base） */
export interface SignItemPayload {
  sku_id: number
  batch_no: string
  sign_qty_base: number
}

/** 签收入参（POST /deliveries/{id}/sign，带明细实收数量） */
export interface SignPayload {
  items: SignItemPayload[]
  remark?: string | null
}

/** 签收明细（§7.4 sign_item；diff_qty_base = 应送 - 实收，正数少送、负数多收） */
export interface SignItem {
  id?: number
  sign_id?: number
  sku_id: number
  batch_no: string
  send_qty_base: number
  sign_qty_base: number
  diff_qty_base?: number | null
  sku_name?: string | null
}

/** 签收单（§7.4 sign：电子 POD，与配送单 1:1） */
export interface Sign {
  id: number
  delivery_id: number
  store_id: number
  sign_by?: number | null
  sign_at?: string | null
  status: SignStatus
  remark?: string | null
  items?: SignItem[]
  store_name?: string | null
}

/** 报损单（§7.5 loss） */
export interface Loss {
  id: number
  loss_no: string
  store_id: number
  sku_id: number
  batch_no?: string | null
  /** 报损数量（基础单位） */
  qty_base: number
  type: LossType
  reason?: string | null
  status: LossStatus
  approved_by?: number | null
  approved_at?: string | null
  created_at?: string | null
  store_name?: string | null
  sku_name?: string | null
}

/** 提交报损入参（POST /losses） */
export interface LossCreatePayload {
  store_id: number
  sku_id: number
  batch_no?: string | null
  qty_base: number
  type: LossType
  reason?: string | null
}

/** 报损查询参数（§8.2 GET /losses?store_id=&status=） */
export interface LossQuery extends PageQuery {
  store_id?: number
  status?: LossStatus
}

// ---------- 配送单 ----------

/**
 * POST /deliveries 生成配送单（装车）。
 * 幂等：delivery 表有 idempotency_key 列（uk_idem），重试须复用同一个 key。
 */
export function createDelivery(
  data: DeliveryCreatePayload,
  idempotencyKey: string = newIdempotencyKey()
): Promise<Delivery> {
  return request<Delivery>({
    url: '/deliveries',
    method: 'post',
    data,
    headers: { 'Idempotency-Key': idempotencyKey }
  })
}

/**
 * GET /deliveries?driver_id=&require_date= 配送单列表（司机当日任务同此接口）。
 * §8.2 未声明该列表的分页参数，若后端返回数组则在此归一为分页形状，页面只面对一种结构。
 */
export async function listDeliveries(params: DeliveryQuery = {}): Promise<PageResult<Delivery>> {
  const data = await request<PageResult<Delivery> | Delivery[]>({
    url: '/deliveries',
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

/** GET /deliveries/{id} 配送单详情（含明细） */
export function getDelivery(id: number): Promise<Delivery> {
  return request<Delivery>({ url: '/deliveries/' + id, method: 'get' })
}

/**
 * POST /deliveries/{id}/depart 发车（loaded→on_way）。
 * 状态流转由后端状态机校验（非法流转返回 40900），故不额外带幂等键。
 */
export function departDelivery(id: number): Promise<Delivery> {
  return request<Delivery>({ url: '/deliveries/' + id + '/depart', method: 'post' })
}

/**
 * POST /deliveries/{id}/sign 签收（带明细实收数量，幂等）。
 * 同一张配送单只允许签一次（§7.4 uk_delivery），重复提交须复用同一个 key。
 */
export function signDelivery(
  id: number,
  data: SignPayload,
  idempotencyKey: string = newIdempotencyKey()
): Promise<Sign> {
  return request<Sign>({
    url: '/deliveries/' + id + '/sign',
    method: 'post',
    data,
    headers: { 'Idempotency-Key': idempotencyKey }
  })
}

/** GET /signs/{id} 签收单详情 */
export function getSign(id: number): Promise<Sign> {
  return request<Sign>({ url: '/signs/' + id, method: 'get' })
}

// ---------- 报损 ----------

/**
 * POST /losses 门店提交报损（draft）。
 * 幂等：loss 表有 idempotency_key 列（uk_idem），重复提交须复用同一个 key。
 */
export function createLoss(
  data: LossCreatePayload,
  idempotencyKey: string = newIdempotencyKey()
): Promise<Loss> {
  return request<Loss>({
    url: '/losses',
    method: 'post',
    data,
    headers: { 'Idempotency-Key': idempotencyKey }
  })
}

/** GET /losses?store_id=&status= 查报损（分页形状归一，同配送单列表） */
export async function listLosses(params: LossQuery = {}): Promise<PageResult<Loss>> {
  const data = await request<PageResult<Loss> | Loss[]>({
    url: '/losses',
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
 * POST /losses/{id}/approve 总部审批（扣批次库存 + 写 batch_flow 流水）。
 * 审批是状态流转（draft→approved），由后端状态机兜底，不带幂等键。
 */
export function approveLoss(id: number): Promise<Loss> {
  return request<Loss>({ url: '/losses/' + id + '/approve', method: 'post' })
}
