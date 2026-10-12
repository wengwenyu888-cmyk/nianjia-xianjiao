// 库存 API（docs/02 §7.2 批次库存 batch_stock + 批次流水 batch_flow；§8.2 库存端点，全部 GET、只读）
// 契约：GET /stocks?store_id=&sku_id=&batch_no=&expire_within_hours=&include_zero=&page=&page_size=
//       GET /stocks/alerts?store_id=&expire_hours=24&low_qty_base=20&limit=50
//       GET /stock-flows?store_id=&sku_id=&batch_no=&flow_type=&page=&page_size=
// 统一响应 { code, message, data } 由 request.ts 解包，本文件只声明契约类型与请求路径。
import { request } from '@/api/request'
import type { PageQuery, PageResult } from '@/api/store'

/** 批次库存（StockOut）：一行 = 门店 × SKU × 批次；qty_base 为结存（基础单位） */
export interface Stock {
  id: number
  /** 0 = 总部仓，其余 = 门店 ID */
  store_id: number
  store_name?: string | null
  sku_id: number
  sku_no?: string | null
  sku_name?: string | null
  /** 批次号（追溯主键） */
  batch_no: string
  /** 结存数量（基础单位） */
  qty_base: number
  /** 展示单位 */
  unit?: string | null
  /** 换算系数 = 1 展示单位对应多少基础单位 */
  convert_factor?: number | null
  /** 保质期至 YYYY-MM-DD HH:mm:ss */
  expire_at?: string | null
  /** 距到期剩余小时（已过期为负） */
  hours_to_expire?: number | null
  /** 后端判定的临期标记 */
  expiring?: boolean | null
  created_at?: string | null
}

/** GET /stocks 查询参数（只读） */
export interface StockQuery extends PageQuery {
  store_id?: number
  sku_id?: number
  batch_no?: string
  /** 只看 N 小时内到期的批次（临期筛选） */
  expire_within_hours?: number
  /** 是否包含零库存批次，缺省 false */
  include_zero?: boolean
}

/** 低库存 SKU（StockAlerts.low_stock[]） */
export interface LowStockItem {
  sku_id: number
  sku_no?: string | null
  sku_name?: string | null
  /** 该 SKU 合计结存（基础单位） */
  qty_base: number
  unit?: string | null
  /** 命中的阈值（基础单位） */
  threshold?: number | null
  /** 涉及批次数 */
  batch_count?: number | null
}

/** 预警汇总（StockAlerts.summary） */
export interface StockAlertSummary {
  expiring_count: number
  low_stock_count: number
  /** 生效的临期小时阈值 */
  expire_hours: number
  /** 生效的低库存阈值（基础单位） */
  low_qty_base: number
  /** 统计时点 */
  as_of: string
}

/** GET /stocks/alerts 响应：临期批次 + 低库存 SKU + 汇总 */
export interface StockAlerts {
  expiring: Stock[]
  low_stock: LowStockItem[]
  summary: StockAlertSummary
}

/** GET /stocks/alerts 查询参数（缺省值即后端默认：24 小时 / 20 基础单位 / 50 条） */
export interface StockAlertQuery {
  store_id?: number
  /** 临期小时阈值，默认 24 */
  expire_hours?: number
  /** 低库存阈值（基础单位），默认 20 */
  low_qty_base?: number
  /** 每类最多返回条数，默认 50 */
  limit?: number
}

/** 流水类型（batch_flow.flow_type）：收货加 / 分拣减 / 报损减 / 盘点调整 */
export type StockFlowType = 'receive_add' | 'pick_sub' | 'loss_sub' | 'count_adjust'

/** 批次流水（StockFlowOut，append-only 台账：谁操作、依据哪张单） */
export interface StockFlow {
  id: number
  store_id: number
  store_name?: string | null
  sku_id: number
  sku_no?: string | null
  sku_name?: string | null
  batch_no: string
  flow_type: StockFlowType
  /** 变动量（基础单位）：加为正、减为负 */
  qty_change_base: number
  /** 本次变动后结存（基础单位） */
  qty_after_base: number
  /** 关联单据类型：purchase_order / pick / loss / stock_count / other */
  doc_type: string
  /** 关联单据号（人可读的追溯入口） */
  doc_no: string
  /** 操作人 user_id */
  operate_by: number
  occurred_at: string
  remark?: string | null
}

/** GET /stock-flows 查询参数 */
export interface StockFlowQuery extends PageQuery {
  store_id?: number
  sku_id?: number
  batch_no?: string
  flow_type?: StockFlowType
}

/** GET /stocks 批次库存分页列表（只读） */
export function listStocks(params: StockQuery = {}): Promise<PageResult<Stock>> {
  return request<PageResult<Stock>>({ url: '/stocks', method: 'get', params })
}

/** GET /stocks/alerts 临期 + 低库存预警（只读） */
export function getStockAlerts(params: StockAlertQuery = {}): Promise<StockAlerts> {
  return request<StockAlerts>({ url: '/stocks/alerts', method: 'get', params })
}

/** GET /stock-flows 批次流水分页列表（只读，按发生时间倒序由后端保证） */
export function listStockFlows(params: StockFlowQuery = {}): Promise<PageResult<StockFlow>> {
  return request<PageResult<StockFlow>>({ url: '/stock-flows', method: 'get', params })
}
