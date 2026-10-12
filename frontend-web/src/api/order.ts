// 要货 / 汇总 / 分拣 API（docs/02 §8.2「要货」+「汇总分拣」端点）
// 契约来源：backend/app/schema/order.py、backend/app/schema/summary.py（api 层端点见 backend/app/api/v1/）。
// 统一响应 { code, message, data } 由 request.ts 解包；写接口按 §8.1 附带 Idempotency-Key（≤64 字符）。
import { request } from '@/api/request'
import type { PageQuery, PageResult } from '@/api/store'

// ---------- 状态机与枚举（§7.3 order_head.status / summary.status / §7.4 pick.status） ----------

/** 要货单状态：draft 草稿 → confirmed 店长确认生效 → merged 已汇总 / cancelled 取消 */
export type OrderStatus = 'draft' | 'confirmed' | 'merged' | 'cancelled'

/** 要货来源：manual 人工创建 / agent 采纳智能体建议 */
export type OrderSource = 'manual' | 'agent'

/** 汇总单状态：generated → picking → picked → delivering → done */
export type SummaryStatus = 'generated' | 'picking' | 'picked' | 'delivering' | 'done'

/** 分拣单状态：created → picking → done / cancelled */
export type PickStatus = 'created' | 'picking' | 'done' | 'cancelled'

// ---------- 要货单（OrderOut / OrderItemOut） ----------

/**
 * 要货单明细（order_item）：qty_unit 按订货单位记，qty_base 由服务层按 convert_factor 换算。
 * 注意：后端不返回 sku_no/sku_name（OrderItemOut 无展示字段），页面用本地 SKU 列表按 sku_id 解析名称。
 */
export interface OrderItem {
  id?: number
  order_id?: number
  sku_id: number
  /** 基础单位数量（服务层换算，只读） */
  qty_base?: number
  /** 按 unit 计的数量 */
  qty_unit: number
  /** 订货单位（sku.unit 或 base_unit） */
  unit: string
  /** 总部分拣后回填的实际批次号（§7.3：追溯闭环第一环） */
  batch_no?: string | null
}

/** 要货单头（order_head）：后端不返回门店名称，页面用本地门店列表按 store_id 解析 */
export interface Order {
  id: number
  order_no: string
  store_id: number
  /** 需求配送日 YYYY-MM-DD */
  require_date: string
  status: OrderStatus
  source: OrderSource
  /** 采纳的智能体建议 id（source=agent 时有值） */
  agent_suggestion_id?: number | null
  /** 店长确认人 / 确认时间 */
  confirm_by?: number | null
  confirm_at?: string | null
  /** 乐观锁版本令牌：修改草稿时需要回传（不一致 40900） */
  version?: number | null
  created_by?: number | null
  created_at?: string | null
  updated_at?: string | null
  items?: OrderItem[]
}

/** 明细入参（OrderItemIn）：换算在服务层，qty_base 一般不用传 */
export interface OrderItemPayload {
  sku_id: number
  qty_unit: number
  unit?: string | null
}

/** POST /orders 入参（OrderCreate）：门店账号可省略 store_id（后端取本人 store_id） */
export interface OrderPayload {
  store_id?: number
  require_date: string
  items: OrderItemPayload[]
}

/** PUT /orders/{id} 入参（OrderUpdate）：items 传入即整单覆盖；version 做乐观锁 */
export interface OrderUpdatePayload {
  require_date?: string
  items?: OrderItemPayload[]
  version?: number | null
}

/** GET /orders?store_id=&require_date=&status= 查询参数 */
export interface OrderQuery extends PageQuery {
  store_id?: number
  require_date?: string
  status?: OrderStatus
}

// ---------- 汇总单（SummaryOut / SummaryItemOut） ----------

/** 汇总明细（summary_item：SKU × 总量；批次分配留到分拣环节） */
export interface SummaryItem {
  id?: number
  summary_id?: number
  sku_id: number
  /** 该 SKU 当日要货总量（基础单位） */
  total_qty_base: number
  /** 展示字段：后端 summary_item 未返回，页面用本地 SKU 列表解析；有值时直接展示 */
  sku_no?: string | null
  sku_name?: string | null
  base_unit?: string | null
  /** 涉及门店数：summary_item 未存该列（后端未返回），有值时页面展示该列，否则整列隐藏 */
  store_count?: number | null
}

/** 汇总单头（summary：每配送日一张，uk_req_date） */
export interface Summary {
  id: number
  summary_no: string
  require_date: string
  status: SummaryStatus
  /** 汇总行数（SKU 数） */
  line_count: number
  created_at?: string | null
  updated_at?: string | null
  items?: SummaryItem[]
}

/** GET /summaries?require_date=&status= 查询参数 */
export interface SummaryQuery extends PageQuery {
  require_date?: string
  status?: SummaryStatus
}

// ---------- 分拣单（PickOut / PickItemOut） ----------

/** 分拣明细（pick_item：批次在此落定，FIFO 按 expire_at 升序取批） */
export interface PickItem {
  id?: number
  pick_id?: number
  sku_id: number
  /** 实际拣出的批次号 */
  batch_no: string
  /** 拣出数量（基础单位） */
  qty_base: number
  /** 展示字段：后端 pick_item 未返回，页面用本地 SKU 列表解析；有值时直接展示 */
  sku_name?: string | null
  base_unit?: string | null
  /** 批次到期时间：后端 pick_item 未返回（FIFO 依据），有值时按它升序展示 */
  expire_at?: string | null
}

/** 分拣单头（pick：一张汇总单按门店拆多张） */
export interface PickOrder {
  id: number
  pick_no: string
  summary_id: number
  store_id: number
  status: PickStatus
  version?: number | null
  created_at?: string | null
  updated_at?: string | null
  items?: PickItem[]
  /** 展示字段：后端 PickOut 未返回，页面用本地汇总/门店列表按 id 解析；有值时直接展示 */
  summary_no?: string | null
  require_date?: string | null
  store_name?: string | null
}

/** POST /picks 入参（PickCreate）：按门店生成分拣单（锁批次扣库存，事务） */
export interface PickPayload {
  summary_id: number
  store_id: number
}

/** GET /picks 查询参数 */
export interface PickQuery extends PageQuery {
  require_date?: string
  status?: PickStatus
  summary_id?: number
  store_id?: number
}

/** 完成分拣时回传的实拣明细（后端 POST /picks/{id}/complete 当前不接收请求体） */
export interface PickCompletePayload {
  items?: { sku_id: number; batch_no: string; qty_base: number }[]
}

// ---------- 幂等键与列表归一化 ----------

/**
 * 生成一个 Idempotency-Key（§8.1：写接口支持，重复请求返回首次结果）。
 * 优先真随机 UUID；局域网 http 访问下 crypto.randomUUID 不可用时回退时间戳 + 随机串。
 * 同一操作重试时把首次的 key 传回，后端即返回首次结果而不是重复建单。
 */
export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return 'njxj-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10)
}

/** 列表响应归一化：§8.1 约定 { list, total, page, page_size }；后端直返数组时补齐外壳（同 store.ts getPrices 策略） */
function toPage<T>(data: PageResult<T> | T[] | null | undefined, params: PageQuery): PageResult<T> {
  if (Array.isArray(data)) {
    return {
      list: data,
      total: data.length,
      page: params.page ?? 1,
      page_size: params.page_size ?? data.length
    }
  }
  return {
    list: data?.list ?? [],
    total: data?.total ?? 0,
    page: data?.page ?? params.page ?? 1,
    page_size: data?.page_size ?? params.page_size ?? 20
  }
}

// ---------- 要货单端点（§8.2 要货） ----------

/** POST /orders 门店提交要货单 draft（幂等） */
export function createOrder(
  data: OrderPayload,
  idempotencyKey: string = newIdempotencyKey()
): Promise<Order> {
  return request<Order>({
    url: '/orders',
    method: 'post',
    data,
    headers: { 'Idempotency-Key': idempotencyKey }
  })
}

/** GET /orders?store_id=&require_date=&status= 查要货单（store_manager 限本店，见 §8.1 数据范围） */
export async function listOrders(params: OrderQuery = {}): Promise<PageResult<Order>> {
  const data = await request<PageResult<Order> | Order[]>({ url: '/orders', method: 'get', params })
  return toPage<Order>(data, params)
}

/**
 * GET /orders/{id} 要货单详情（含明细）。
 * 现状（已核对 backend/app/api/v1/orders.py）：§8.2 未列该端点，后端也未实现；
 * service 层有 get_order，列表接口已随行返回 items，故页面不需要它。
 * 该函数留作契约占位：后端补上详情端点后可直接使用，不改页面。
 */
export function getOrder(id: number): Promise<Order> {
  return request<Order>({ url: '/orders/' + id, method: 'get' })
}

/** PUT /orders/{id} 修改草稿明细（仅 draft；items 整单覆盖，version 乐观锁） */
export function updateOrder(id: number, data: OrderUpdatePayload): Promise<Order> {
  return request<Order>({ url: '/orders/' + id, method: 'put', data })
}

/** POST /orders/{id}/confirm 店长确认生效（draft → confirmed） */
export function confirmOrder(id: number): Promise<Order> {
  return request<Order>({ url: '/orders/' + id + '/confirm', method: 'post' })
}

/** POST /orders/{id}/cancel 取消（仅 confirmed 前） */
export function cancelOrder(id: number): Promise<Order> {
  return request<Order>({ url: '/orders/' + id + '/cancel', method: 'post' })
}

// ---------- 汇总单端点（§8.2 汇总分拣） ----------

/** POST /summaries/generate 按 require_date 汇总当日全部 confirmed 要货单（一个配送日只落一张） */
export function generateSummary(
  requireDate: string,
  idempotencyKey: string = newIdempotencyKey()
): Promise<Summary> {
  return request<Summary>({
    url: '/summaries/generate',
    method: 'post',
    data: { require_date: requireDate },
    headers: { 'Idempotency-Key': idempotencyKey }
  })
}

/** GET /summaries?require_date=&status= 查汇总单（含 SKU 汇总明细 items） */
export async function listSummaries(params: SummaryQuery = {}): Promise<PageResult<Summary>> {
  const data = await request<PageResult<Summary> | Summary[]>({
    url: '/summaries',
    method: 'get',
    params
  })
  return toPage<Summary>(data, params)
}

// ---------- 分拣单端点（§8.2 汇总分拣） ----------

/** POST /picks 按门店生成分拣单（FIFO 锁批次扣库存，事务） */
export function createPick(
  data: PickPayload,
  idempotencyKey: string = newIdempotencyKey()
): Promise<PickOrder> {
  return request<PickOrder>({
    url: '/picks',
    method: 'post',
    data,
    headers: { 'Idempotency-Key': idempotencyKey }
  })
}

/**
 * GET /picks?require_date=&status= 分拣单列表。
 * 现状（已核对 backend/app/api/v1/picking.py）：§8.2 只列了 POST /picks 与 POST /picks/{id}/complete，
 * 后端尚未实现该读端点（schema/summary.py 已有 PickPage 契约，标注"契约先行"）。
 * 页面已对该情况做降级：请求失败时给出行内提示，不影响「新建分拣单 / 完成分拣」。
 */
export async function listPicks(params: PickQuery = {}): Promise<PageResult<PickOrder>> {
  const data = await request<PageResult<PickOrder> | PickOrder[]>({
    url: '/picks',
    method: 'get',
    params
  })
  return toPage<PickOrder>(data, params)
}

/** POST /picks/{id}/complete 分拣完成（created/picking → done） */
export function completePick(id: number, data: PickCompletePayload = {}): Promise<PickOrder> {
  return request<PickOrder>({ url: '/picks/' + id + '/complete', method: 'post', data })
}
