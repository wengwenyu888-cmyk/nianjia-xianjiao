// 智能体 API（docs/02 §8.2「智能体」端点）
// 契约来源：backend/app/schema/agent.py（SuggestionOut / PickPlanOut）+ backend/app/service/agent_service.py（payload 快照形状）。
// 「只建议不落账」：建议不产生有效单据；apply 只生成 draft 要货单，仍须 order:confirm 才生效。
import { request } from '@/api/request'
import { newIdempotencyKey, type Order } from '@/api/order'

/** 建议类型：order_suggest 要货建议 / pick_plan 配货分拣计划建议（只读预演） */
export type SuggestionType = 'order_suggest' | 'pick_plan'

/** 应用状态：pending 待处理 / applied 已采纳 / rejected 已拒绝 / expired 已过期 */
export type ApplyStatus = 'pending' | 'applied' | 'rejected' | 'expired'

/**
 * 要货建议明细条目（agent_suggestion.payload.items[]）。
 * 数值列在后端以字符串落 JSON 快照（Decimal → str），页面按字符串展示、比较前自行转数字。
 */
export interface SuggestionItem {
  sku_id: number
  sku_no?: string | null
  sku_name?: string | null
  /** 订货单位 */
  unit?: string | null
  base_unit?: string | null
  convert_factor?: string | null
  observed_days?: number | null
  history_qty_base?: string | null
  avg_qty_base?: string | null
  weekday_factor?: string | null
  weekday_qty_base?: string | null
  /** 建议量（基础单位） */
  suggest_qty_base?: string | null
  /** 建议量（订货单位）——卡片主展示；apply 时后端按它建要货明细 */
  suggest_qty_unit?: string | null
  /** 总部仓未过期可发量（基础单位） */
  hq_available_qty_base?: string | null
  /** 最近到期批次时间（临期提醒） */
  nearest_expire_at?: string | null
  shelf_life_hours?: number | null
  /** 风险提示（库存不足、24 小时内到期批次等） */
  flags?: string[]
  /** 生成依据说明 */
  reason?: string | null
}

/** 要货建议 payload 快照（按店按日的依据：销量/库存/效期 + 理由） */
export interface SuggestionPayload {
  policy?: string | null
  generated_at?: string | null
  store_id?: number | null
  require_date?: string | null
  lookback_days?: number | null
  weekday_factor?: string | null
  basis?: string | null
  items?: SuggestionItem[]
  /** 因总部仓无可发量等原因未进入建议明细的 SKU */
  skipped?: SuggestionItem[]
  /** 全局提示（如"该店近 7 天没有要货记录"） */
  warnings?: string[]
  totals?: { item_count?: number | null; suggest_qty_base?: string | null } | null
}

/** 建议快照响应体（SuggestionOut，对应 agent_suggestion 表） */
export interface AgentSuggestion {
  id: number
  suggestion_type: SuggestionType
  /** 建议对象门店；0 = 总部/全局（配货计划 WAREHOUSE_STORE_ID） */
  store_id: number
  require_date?: string | null
  payload?: SuggestionPayload | null
  apply_status: ApplyStatus
  applied_by?: number | null
  applied_at?: string | null
  /** apply 生成的 draft 要货单 id */
  order_id?: number | null
  /** 生成所用规则/提示词版本，如 rule-v1 */
  model?: string | null
  version?: number | null
  created_at?: string | null
  updated_at?: string | null
}

/** 分拣预演命中的批次行（PickPlanBatchOut，只读快照） */
export interface PickPlanBatch {
  batch_no: string
  /** 预演分配数量（基础单位，字符串小数） */
  qty_base: string
  /** 该批次保质期至 */
  expire_at?: string | null
  produced_at?: string | null
}

/** 分拣预演任务行（PickPlanTaskOut：门店×SKU 需求量与 FIFO 批次分配） */
export interface PickPlanTask {
  store_id: number
  sku_id: number
  /** 该门店该 SKU 当日要货量（基础单位） */
  required_qty_base: string
  /** 预演可分配量（基础单位） */
  allocated_qty_base: string
  /** 预演缺口（基础单位），>0 表示总部仓不足 */
  shortage_qty_base: string
  batches?: PickPlanBatch[]
  /** 风险提示（临期批次/缺口等） */
  flags?: string[]
}

/** POST /agent/pick-plan 响应体（PickPlanOut）：FIFO 预演快照，只读不扣库存 */
export interface PickPlan {
  /** 本次预演落库的建议快照 id */
  suggestion_id: number
  require_date: string
  /** 生成策略版本，如 rule-v1 */
  policy: string
  generated_at: string
  tasks?: PickPlanTask[]
  /** 全局提示（如当日无已确认要货单） */
  warnings?: string[]
  total_required_qty_base?: string | null
  total_shortage_qty_base?: string | null
}

/** 取要货建议明细（payload 缺失时返回空数组） */
export function suggestionItems(s: AgentSuggestion | null | undefined): SuggestionItem[] {
  return s?.payload?.items ?? []
}

/** 取"未进入建议"的 SKU（总部仓无可发量等原因被跳过） */
export function suggestionSkipped(s: AgentSuggestion | null | undefined): SuggestionItem[] {
  return s?.payload?.skipped ?? []
}

/** 取建议快照的全局提示 */
export function suggestionWarnings(s: AgentSuggestion | null | undefined): string[] {
  return s?.payload?.warnings ?? []
}

/** POST /agent/order-suggestions 生成要货建议（按店按日），快照落 agent_suggestion(pending) */
export function getOrderSuggestions(
  data: { store_id?: number; require_date: string },
  idempotencyKey: string = newIdempotencyKey()
): Promise<AgentSuggestion> {
  return request<AgentSuggestion>({
    url: '/agent/order-suggestions',
    method: 'post',
    data,
    headers: { 'Idempotency-Key': idempotencyKey }
  })
}

/** GET /agent/order-suggestions/{id} 查看建议快照与依据 */
export function getSuggestion(id: number): Promise<AgentSuggestion> {
  return request<AgentSuggestion>({ url: '/agent/order-suggestions/' + id, method: 'get' })
}

/**
 * POST /agent/order-suggestions/{id}/apply 应用建议 → 生成 draft 要货单。
 * 响应体是 OrderOut（生成的 draft 单，仍须 PUT/confirm 才生效）；重复 apply 返回首次生成的单。
 */
export function applySuggestion(
  id: number,
  idempotencyKey: string = newIdempotencyKey()
): Promise<Order> {
  return request<Order>({
    url: '/agent/order-suggestions/' + id + '/apply',
    method: 'post',
    data: {},
    headers: { 'Idempotency-Key': idempotencyKey }
  })
}

/** POST /agent/pick-plan 配货/分拣批次计划建议（FIFO 预演，只读，落 agent_suggestion(suggestion_type=pick_plan)） */
export function getPickPlan(
  data: { require_date: string },
  idempotencyKey: string = newIdempotencyKey()
): Promise<PickPlan> {
  return request<PickPlan>({
    url: '/agent/pick-plan',
    method: 'post',
    data,
    headers: { 'Idempotency-Key': idempotencyKey }
  })
}
