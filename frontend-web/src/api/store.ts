// 主数据 API（docs/02 §8.2 主数据端点）：门店 / SKU / 供应商 / 价目表
// 统一响应 { code, message, data } 由 request.ts 拦截解包，本文件只声明契约类型与请求路径。
import { request } from '@/api/request'

/** §8.1 分页响应：data = { list, total, page, page_size } */
export interface PageResult<T> {
  list: T[]
  total: number
  page: number
  page_size: number
}

/** §8.1 分页请求参数（page_size 最大 200） */
export interface PageQuery {
  page?: number
  page_size?: number
}

/** 配送节奏（§7.1 store.delivery_cycle）：daily 日配 / every_other_day 隔日配 */
export type DeliveryCycle = 'daily' | 'every_other_day'

/** 供应类型（§7.1 sku.supply_type）：direct 直配 / temp 临采 */
export type SupplyType = 'direct' | 'temp'

/** 价格类型（§7.1 price.price_type）：purchase 采购价 / transfer 内部调拨价 */
export type PriceType = 'purchase' | 'transfer'

// ---------- 门店 ----------

/** 门店（字段对应 §7.1 store 表） */
export interface Store {
  id: number
  store_no: string
  name: string
  region?: string | null
  address?: string | null
  contact_name?: string | null
  contact_phone?: string | null
  delivery_cycle: DeliveryCycle
  status: number
}

/** 新建/修改门店入参 */
export interface StorePayload {
  store_no: string
  name: string
  region?: string | null
  address?: string | null
  contact_name?: string | null
  contact_phone?: string | null
  delivery_cycle: DeliveryCycle
  status?: number
}

/** 门店列表查询参数 */
export interface StoreQuery extends PageQuery {
  /** 关键词：门店编码 / 名称模糊匹配 */
  keyword?: string
}

/** GET /stores 门店分页列表 */
export function getStores(params: StoreQuery = {}): Promise<PageResult<Store>> {
  return request<PageResult<Store>>({ url: '/stores', method: 'get', params })
}

/** POST /stores 新建门店 */
export function createStore(data: StorePayload): Promise<Store> {
  return request<Store>({ url: '/stores', method: 'post', data })
}

/** PUT /stores/{id} 修改门店（配送节奏等） */
export function updateStore(id: number, data: Partial<StorePayload>): Promise<Store> {
  return request<Store>({ url: '/stores/' + id, method: 'put', data })
}

// ---------- 商品 SKU ----------

/** 商品 SKU（数量计算一律按 base_unit；convert_factor = 1 订货单位对应多少基础单位） */
export interface Sku {
  id: number
  sku_no: string
  name: string
  category: string
  spec?: string | null
  unit: string
  base_unit: string
  convert_factor: number
  shelf_life_hours: number
  supply_type: SupplyType
  status: number
}

/** 新建 SKU 入参 */
export interface SkuPayload {
  sku_no: string
  name: string
  category: string
  spec?: string | null
  unit: string
  base_unit: string
  convert_factor: number
  shelf_life_hours: number
  supply_type: SupplyType
  status?: number
}

/** SKU 列表查询参数 */
export interface SkuQuery extends PageQuery {
  category?: string
  /** 关键词：SKU 编码 / 品名模糊匹配 */
  keyword?: string
}

/** GET /skus SKU 列表/筛选 */
export function getSkus(params: SkuQuery = {}): Promise<PageResult<Sku>> {
  return request<PageResult<Sku>>({ url: '/skus', method: 'get', params })
}

/** POST /skus 新建 SKU（单位/换算/保质期） */
export function createSku(data: SkuPayload): Promise<Sku> {
  return request<Sku>({ url: '/skus', method: 'post', data })
}

// ---------- 供应商 ----------

/** 供应商（payment_terms 账期，单位：天） */
export interface Supplier {
  id: number
  supplier_no: string
  name: string
  contact_name?: string | null
  contact_phone?: string | null
  payment_terms: number
  status: number
}

/** 新建供应商入参 */
export interface SupplierPayload {
  supplier_no: string
  name: string
  contact_name?: string | null
  contact_phone?: string | null
  payment_terms: number
  status?: number
}

/** 供应商列表查询参数 */
export interface SupplierQuery extends PageQuery {
  keyword?: string
}

/** GET /suppliers 供应商列表 */
export function getSuppliers(params: SupplierQuery = {}): Promise<PageResult<Supplier>> {
  return request<PageResult<Supplier>>({ url: '/suppliers', method: 'get', params })
}

/** POST /suppliers 新建供应商 */
export function createSupplier(data: SupplierPayload): Promise<Supplier> {
  return request<Supplier>({ url: '/suppliers', method: 'post', data })
}

// ---------- 价目表 ----------

/** 价目（只增不改，带生效区间；effective_to 为 NULL/空表示现行有效） */
export interface Price {
  id: number
  sku_id: number
  price_type: PriceType
  price: number
  effective_from: string
  effective_to?: string | null
}

/** 新增价目入参 */
export interface PricePayload {
  sku_id: number
  price_type: PriceType
  price: number
  effective_from: string
  effective_to?: string | null
}

/** 价目查询参数（§8.2：?sku_id=&date= 查历史当时价） */
export interface PriceQuery extends PageQuery {
  sku_id?: number
  /** YYYY-MM-DD，查该日期的当时价 */
  date?: string
}

/** POST /prices 新增价目（生效区间） */
export function createPrice(data: PricePayload): Promise<Price> {
  return request<Price>({ url: '/prices', method: 'post', data })
}

/**
 * GET /prices?sku_id=&date= 查历史当时价。
 * §8.1 约定分页形状为 { list, total, page, page_size }；若后端直接返回数组，
 * 在此统一归一化，页面只面对一种形状。
 */
export async function getPrices(params: PriceQuery = {}): Promise<PageResult<Price>> {
  const data = await request<PageResult<Price> | Price[]>({
    url: '/prices',
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
