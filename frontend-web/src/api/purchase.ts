// 采购 API（docs/02 §7.2 采购单 + §8.2 采购端点）
// 契约：POST /purchase-orders（Idempotency-Key）· GET /purchase-orders?supplier_id=&status=&page=&page_size=
//       POST /purchase-orders/{id}/receive（items 缺省 = 按采购单明细全量收货）
// 统一响应 { code, message, data } 由 request.ts 解包，本文件只声明契约类型与请求路径。
import { newIdempotencyKey } from '@/api/order'
import { request } from '@/api/request'
import type { PageQuery, PageResult } from '@/api/store'

/**
 * 采购单状态：draft 待收货 → submitted 已提交 → received 已收货 / cancelled 已取消。
 * 定稿契约列了 draft/received/cancelled 三态；后端 schema（backend/app/schema/purchase.py
 * 的 PurchaseStatusValue）另含 submitted，前端按并集收口，未知取值页面原样回退显示。
 */
export type PurchaseOrderStatus = 'draft' | 'submitted' | 'received' | 'cancelled'

/** 采购单明细（PurchaseOrderOut.items[]）：后端已带 sku_no/sku_name，缺失时页面才回退本地 SKU 字典 */
export interface PurchaseOrderItem {
  id: number
  sku_id: number
  sku_no?: string | null
  sku_name?: string | null
  /** 按订货单位计的数量 */
  qty_unit: number
  /** 订货单位（sku.unit 或 base_unit） */
  unit: string
  /** 基础单位数量（服务层按 convert_factor 换算，只读） */
  qty_base: number
  /** 已收数量（基础单位，分批收货用；本次可收量 = qty_base − received_qty_base） */
  received_qty_base: number
  /** 下单单价（元/展示单位） */
  unit_price: number
  /** 行金额 = qty_unit × unit_price */
  amount: number
}

/** 采购单头（PurchaseOrderOut） */
export interface PurchaseOrder {
  id: number
  po_no: string
  supplier_id: number
  /** 展示字段：优先后端值，缺失时页面回退本地供应商字典 */
  supplier_name?: string | null
  status: PurchaseOrderStatus
  /** 预计到货日 YYYY-MM-DD */
  expected_date?: string | null
  remark?: string | null
  /** 采购单总金额（元） */
  total_amount: number
  items?: PurchaseOrderItem[]
}

/** POST /purchase-orders 明细入参：unit_price 可空 = 后端取价目表现行价 */
export interface PurchaseOrderItemPayload {
  sku_id: number
  qty_unit: number
  unit?: string | null
  unit_price?: number | null
}

/** POST /purchase-orders 入参 */
export interface PurchaseOrderPayload {
  supplier_id: number
  expected_date?: string | null
  remark?: string | null
  items: PurchaseOrderItemPayload[]
}

/** GET /purchase-orders 查询参数 */
export interface PurchaseOrderQuery extends PageQuery {
  supplier_id?: number
  status?: PurchaseOrderStatus
}

/** POST /purchase-orders/{id}/receive 收货明细入参（数量按基础单位） */
export interface PurchaseReceiveItemPayload {
  sku_id: number
  qty_base: number
  /** 保质期至 YYYY-MM-DD HH:mm:ss（批次临期预警依据） */
  expire_at: string
  /** 收货单价，可空（缺省沿用采购单行价） */
  unit_price?: number | null
}

/** POST /purchase-orders/{id}/receive 入参：items 缺省 = 按采购单明细全量收货 */
export interface PurchaseReceivePayload {
  /** 批次号前缀，可空 = 后端按规则生成 */
  batch_no_prefix?: string | null
  /** 整单保质期至（items 内逐行可覆盖） */
  expire_at?: string | null
  items?: PurchaseReceiveItemPayload[]
}

/** POST /purchase-orders 新建采购单（幂等：同 key 重复提交返回首次建单结果） */
export function createPurchaseOrder(
  data: PurchaseOrderPayload,
  idempotencyKey: string = newIdempotencyKey()
): Promise<PurchaseOrder> {
  return request<PurchaseOrder>({
    url: '/purchase-orders',
    method: 'post',
    data,
    headers: { 'Idempotency-Key': idempotencyKey }
  })
}

/** GET /purchase-orders?supplier_id=&status=&page=&page_size= 采购单分页列表 */
export function listPurchaseOrders(
  params: PurchaseOrderQuery = {}
): Promise<PageResult<PurchaseOrder>> {
  return request<PageResult<PurchaseOrder>>({ url: '/purchase-orders', method: 'get', params })
}

/**
 * POST /purchase-orders/{id}/receive 收货入库（draft → received）。
 * 后端在同一事务内生成批次库存 batch_stock + 写批次流水 batch_flow(receive_add)；
 * items 缺省时按采购单明细全量收货。契约未要求该端点带幂等键，故不附加请求头。
 */
export function receivePurchaseOrder(
  id: number,
  data: PurchaseReceivePayload = {}
): Promise<PurchaseOrder> {
  return request<PurchaseOrder>({
    url: '/purchase-orders/' + id + '/receive',
    method: 'post',
    data
  })
}
