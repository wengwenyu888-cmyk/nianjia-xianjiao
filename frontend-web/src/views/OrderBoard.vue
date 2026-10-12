<script setup lang="ts">
// 门店要货工作台（docs/02 §8.2「要货」+「智能体」端点）
// 主流程：选配送日期 → 获取 AI 建议 → 应用生成 draft 单 → 编辑明细 → 确认要货 / 取消
// 视觉：延续 docs/07 V3（毛玻璃顶栏 + 白卡片 16px 圆角 + 品牌绿，奶油白底由全局主题给）
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  applySuggestion,
  getOrderSuggestions,
  suggestionItems,
  suggestionSkipped,
  suggestionWarnings,
  type AgentSuggestion,
  type SuggestionItem
} from '@/api/agent'
import {
  cancelOrder,
  confirmOrder,
  createOrder,
  listOrders,
  updateOrder,
  type Order,
  type OrderItemPayload,
  type OrderStatus
} from '@/api/order'
import { getSkus, getStores, type Sku, type Store } from '@/api/store'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()

// ---------- 角色与数据范围（§8.1：user.store_id 非空即限本店） ----------

/** 门店账号绑定的门店 id；为空表示总部账号（admin/ops），需要自己选门店 */
const boundStoreId = computed<number | null>(() => userStore.user?.store_id ?? null)

/**
 * 权限点判定（§8.3）：要货写动作默认只授予 store_manager（admin 为全量权限点）。
 * 权限点列表为空（旧缓存 / 尚未拉取用户信息）时放宽，避免把合法用户锁在只读态。
 */
function hasPerm(code: string): boolean {
  const codes = userStore.permissionCodes
  return codes.length === 0 || codes.includes(code)
}

/** 能否写要货单（order:create/update/confirm/cancel 同属一组） */
const canOrderWrite = computed<boolean>(() => hasPerm('order:create'))
/** 能否采纳建议（agent:apply） */
const canApply = computed<boolean>(() => hasPerm('agent:apply'))

// ---------- 基础工具 ----------

/** 日期偏移（YYYY-MM-DD），不引第三方日期库 */
function dateOffset(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() + days)
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return String(d.getFullYear()) + '-' + month + '-' + day
}

/**
 * 数量显示：最多 3 位小数、去掉多余 0（对应 DECIMAL(14,3)）。
 * 建议快照里的数量是字符串（Decimal → str），要货明细里是数字（JSON 数字），两种都接。
 */
function numText(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  return String(Number(n.toFixed(3)))
}

/** 要货单状态显示（与 §7.3 order_head.status 枚举一一对应） */
const ORDER_STATUS: Record<OrderStatus, { text: string; type: 'info' | 'success' | 'warning' | 'danger' }> = {
  draft: { text: '草稿', type: 'info' },
  confirmed: { text: '已确认', type: 'success' },
  merged: { text: '已汇总', type: 'warning' },
  cancelled: { text: '已取消', type: 'danger' }
}

function orderStatusText(s: OrderStatus | null | undefined): string {
  return s && ORDER_STATUS[s] ? ORDER_STATUS[s].text : '—'
}

function orderStatusType(s: OrderStatus | null | undefined): 'info' | 'success' | 'warning' | 'danger' {
  return s && ORDER_STATUS[s] ? ORDER_STATUS[s].type : 'info'
}

/** 要货来源显示 */
function sourceText(row: Order): string {
  return row.source === 'agent' ? 'AI 建议' : '人工'
}

// ---------- 顶部条件区 ----------

/** 配送日期：默认次日（要货提前一天报，配送日 = 明日） */
const requireDate = ref<string>(dateOffset(1))
/** 总部账号的手选门店 */
const selectedStoreId = ref<number | null>(null)
/** 当前生效门店：门店账号取绑定门店，总部账号取手选门店 */
const activeStoreId = computed<number | null>(() => boundStoreId.value ?? selectedStoreId.value)

const storeOptions = ref<Store[]>([])
const storeLoading = ref(false)

/** 门店显示名：优先取门店列表；门店账号（无门店列表权限）回退为「本店（#id）」 */
const storeLabel = computed<string>(() => {
  const id = activeStoreId.value
  if (id === null) return '未选择'
  const hit = storeOptions.value.find((s) => s.id === id)
  if (hit) return hit.name
  return boundStoreId.value !== null ? '本店（#' + id + '）' : '门店 #' + id
})

/** 门店列表仅在总部账号下加载（门店账号无 master:store:read，不必请求） */
async function loadStoreOptions(): Promise<void> {
  if (boundStoreId.value !== null) return
  storeLoading.value = true
  try {
    const res = await getStores({ page: 1, page_size: 200 })
    storeOptions.value = res.list
    if (selectedStoreId.value === null && storeOptions.value.length > 0) {
      selectedStoreId.value = storeOptions.value[0].id
    }
  } catch {
    // request.ts 已统一弹错；页面降级为"未选择门店"，可见下方空态提示
    storeOptions.value = []
  } finally {
    storeLoading.value = false
  }
}

// ---------- AI 建议（§8.2 智能体） ----------

const suggestLoading = ref(false)
const suggestError = ref(false)
const suggest = ref<AgentSuggestion | null>(null)
const applyingSku = ref<number | null>(null)

/** 建议明细：payload 为 { items } 或数组都由 api 层归一化 */
const adviceItems = computed<SuggestionItem[]>(() => suggestionItems(suggest.value))
/** 建议是否已被采纳（采纳后按钮置灰，避免重复建单） */
const adviceApplied = computed<boolean>(() => suggest.value?.apply_status === 'applied')
/** 快照 id（模板用，避免对 null 取属性） */
const adviceId = computed<number | null>(() => suggest.value?.id ?? null)
/** 生成策略版本（如 rule-v1） */
const adviceModel = computed<string>(() => suggest.value?.model ?? '')
/** 生成依据总述（payload.basis） */
const adviceBasis = computed<string>(() => suggest.value?.payload?.basis ?? '')
/** 全局提示（如"该店近 7 天没有要货记录"） */
const adviceWarnings = computed<string[]>(() => suggestionWarnings(suggest.value))
/** 因总部仓无可发量未进入建议的 SKU 数 */
const adviceSkippedCount = computed<number>(() => suggestionSkipped(suggest.value).length)

async function handleSuggest(): Promise<void> {
  if (activeStoreId.value === null) {
    ElMessage.warning('请先选择门店')
    return
  }
  suggestLoading.value = true
  suggestError.value = false
  try {
    // 快照落 agent_suggestion(pending)，只建议不落账
    suggest.value = await getOrderSuggestions({
      store_id: activeStoreId.value,
      require_date: requireDate.value
    })
    if (adviceItems.value.length === 0) {
      ElMessage.info('已生成建议：当日无需补充要货')
    } else {
      ElMessage.success('已生成 ' + adviceItems.value.length + ' 条要货建议')
    }
  } catch {
    suggest.value = null
    suggestError.value = true
  } finally {
    suggestLoading.value = false
  }
}

/**
 * 应用建议 → draft 要货单。
 * 采纳粒度是「整份快照」（后端 POST /agent/order-suggestions/{id}/apply 按建议 id 建单），
 * 所以每条卡片上的「应用」都会把整份建议一起落成一张 draft 单，页面上有文案说明。
 */
async function handleApply(item: SuggestionItem): Promise<void> {
  const snapshot = suggest.value
  if (!snapshot) return
  if (adviceApplied.value) {
    ElMessage.info('该建议已生成草稿单')
    return
  }
  applyingSku.value = item.sku_id
  try {
    // 响应体即生成的 draft 要货单（OrderOut）；重复 apply 返回首次生成的单
    const order = await applySuggestion(snapshot.id)
    suggest.value = { ...snapshot, apply_status: 'applied', order_id: order.id }
    ElMessage.success('已生成草稿，确认后生效')
    await loadOrders()
    await openDraft(order)
  } catch {
    // request.ts 已弹错；保留卡片可再次点击
  } finally {
    applyingSku.value = null
  }
}

// ---------- 草稿编辑区 ----------

/** 编辑行：数量按订货单位记（换算在服务层） */
interface DraftRow {
  sku_id: number | null
  qty_unit: number
  unit: string
}

/** 明细入参结构：后端 OrderItem 与提交用的 OrderItemPayload 都满足（只取这三个字段） */
interface RowLike {
  sku_id: number
  qty_unit: number
  unit?: string | null
}

const editingOrder = ref<Order | null>(null)
const isNewDraft = ref(false)
const draftRows = ref<DraftRow[]>([])
const saving = ref(false)
const skuOptions = ref<Sku[]>([])
const skuLoading = ref(false)

/** 编辑区是否可改：草稿（或未落库的新草稿）且当前账号有写权限 */
const editableNow = computed<boolean>(
  () => canOrderWrite.value && (isNewDraft.value || editingOrder.value?.status === 'draft')
)
const hasEditor = computed<boolean>(() => isNewDraft.value || editingOrder.value !== null)
/** 编辑区单据号与状态（模板用，避免对 null 取属性） */
const editingNo = computed<string>(() => editingOrder.value?.order_no ?? '')
const editingStatus = computed<OrderStatus | null>(() => editingOrder.value?.status ?? null)

async function loadSkuOptions(): Promise<void> {
  skuLoading.value = true
  try {
    const res = await getSkus({ page: 1, page_size: 200 })
    skuOptions.value = res.list
  } catch {
    skuOptions.value = []
  } finally {
    skuLoading.value = false
  }
}

function skuOf(id: number | null): Sku | undefined {
  if (id === null) return undefined
  return skuOptions.value.find((s) => s.id === id)
}

/** 明细 → 编辑行（unit 缺失时留空，服务器换算口径由 SKU 决定） */
function toRows(items: RowLike[]): DraftRow[] {
  return items.map((it) => ({ sku_id: it.sku_id, qty_unit: it.qty_unit, unit: it.unit ?? '' }))
}

/** 单位下拉：订货单位（带换算说明）+ 基础单位；缺 SKU 时沿用已有单位 */
function unitOptions(row: DraftRow): { value: string; label: string }[] {
  const sku = skuOf(row.sku_id)
  if (!sku) return row.unit ? [{ value: row.unit, label: row.unit }] : []
  const first = sku.unit + (sku.convert_factor > 1 ? '（1' + sku.unit + ' = ' + sku.convert_factor + sku.base_unit + '）' : '')
  const list = [{ value: sku.unit, label: first }]
  if (sku.base_unit !== sku.unit) list.push({ value: sku.base_unit, label: sku.base_unit })
  return list
}

function addRow(): void {
  draftRows.value.push({ sku_id: null, qty_unit: 1, unit: '' })
}

function removeRow(index: number): void {
  draftRows.value.splice(index, 1)
}

/** 选 SKU 后带出默认单位（订货单位），数量为空时给 1 */
function handleSkuChange(row: DraftRow): void {
  const sku = skuOf(row.sku_id)
  if (!sku) return
  row.unit = sku.unit
  if (!row.qty_unit || row.qty_unit <= 0) row.qty_unit = 1
}

/** 组装并校验提交明细：SKU 必选、数量 > 0 */
function buildItems(): OrderItemPayload[] | null {
  if (draftRows.value.length === 0) {
    ElMessage.warning('请至少添加一行明细')
    return null
  }
  const items: OrderItemPayload[] = []
  for (const row of draftRows.value) {
    if (row.sku_id === null) {
      ElMessage.warning('存在未选择 SKU 的明细行')
      return null
    }
    if (!row.qty_unit || row.qty_unit <= 0) {
      ElMessage.warning('明细数量需大于 0')
      return null
    }
    const unit = row.unit || skuOf(row.sku_id)?.unit || ''
    if (!unit) {
      ElMessage.warning('存在未确定单位的明细行，请重新选择 SKU')
      return null
    }
    items.push({ sku_id: row.sku_id, unit, qty_unit: row.qty_unit })
  }
  return items
}

/** 新建本地草稿（未落库，保存时才 POST /orders） */
function handleNewDraft(): void {
  if (activeStoreId.value === null) {
    ElMessage.warning('请先选择门店')
    return
  }
  isNewDraft.value = true
  editingOrder.value = null
  draftRows.value = [{ sku_id: null, qty_unit: 1, unit: '' }]
  ElMessage.info('已新建草稿，填好明细后点「保存草稿」')
}

function closeEditor(): void {
  isNewDraft.value = false
  editingOrder.value = null
  draftRows.value = []
}

/**
 * 载入一张单据到编辑区。
 * 后端列表接口已随行装配 items（order_service.attach_items），无需详情端点；
 * items 为空表示该单据确实没有明细，页面允许手工补行后保存。
 */
async function openDraft(order: Order): Promise<void> {
  isNewDraft.value = false
  editingOrder.value = order
  draftRows.value = toRows(order.items ?? [])
}

/**
 * 落库：新草稿走 POST /orders，已有草稿走 PUT /orders/{id}（明细整体覆盖）。
 * silent = true 时不出成功提示（用于「确认要货」前的静默保存）。
 */
async function persistDraft(silent = false): Promise<Order | null> {
  if (activeStoreId.value === null) {
    ElMessage.warning('请先选择门店')
    return null
  }
  const items = buildItems()
  if (!items) return null
  const creating = isNewDraft.value || editingOrder.value === null
  saving.value = true
  try {
    const saved = creating
      ? await createOrder({
          store_id: activeStoreId.value,
          require_date: requireDate.value,
          items
        })
      : await updateOrder(editingOrder.value!.id, {
          items,
          // 乐观锁：回传列表拿到的 version，不一致后端返回 40900
          version: editingOrder.value!.version ?? null
        })
    if (!silent) {
      ElMessage.success(creating ? '草稿已创建，确认后生效' : '草稿明细已保存')
    }
    isNewDraft.value = false
    editingOrder.value = saved
    draftRows.value = toRows(saved.items ?? items)
    await loadOrders()
    return saved
  } catch {
    // 40900（幂等键重复/状态冲突）、40000（校验失败）等由 request.ts 统一提示
    return null
  } finally {
    saving.value = false
  }
}

/** 确认指定单据：确认弹窗 → POST /orders/{id}/confirm → 刷新列表并回填编辑区 */
async function confirmTarget(target: Order): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '确认后单据生效并进入汇总流程，明细不可再修改。',
      '确认要货（' + target.order_no + '）',
      { type: 'warning', confirmButtonText: '确认要货', cancelButtonText: '再想想' }
    )
  } catch {
    return
  }
  saving.value = true
  try {
    await confirmOrder(target.id)
    ElMessage.success('要货单已确认生效')
    await loadOrders()
    const row = orders.value.find((o) => o.id === target.id)
    if (row) await openDraft(row)
    else if (editingOrder.value && editingOrder.value.id === target.id) {
      editingOrder.value = { ...target, status: 'confirmed' }
    }
  } catch {
    // 40900 状态机非法流转等由 request.ts 提示
  } finally {
    saving.value = false
  }
}

/** 取消指定单据（仅 confirmed 前，§8.2） */
async function cancelTarget(target: Order): Promise<void> {
  try {
    await ElMessageBox.confirm('取消后该单据作废，需要重新提交。', '取消要货单（' + target.order_no + '）', {
      type: 'warning',
      confirmButtonText: '取消单据',
      cancelButtonText: '返回'
    })
  } catch {
    return
  }
  saving.value = true
  try {
    await cancelOrder(target.id)
    ElMessage.success('要货单已取消')
    await loadOrders()
    const row = orders.value.find((o) => o.id === target.id)
    if (row) await openDraft(row)
    else if (editingOrder.value && editingOrder.value.id === target.id) {
      editingOrder.value = { ...target, status: 'cancelled' }
    }
  } catch {
    // request.ts 已提示
  } finally {
    saving.value = false
  }
}

/** 编辑区「确认要货」：未落库的新草稿先保存再确认（confirm 只作用于已存在的单） */
async function handleConfirmEditing(): Promise<void> {
  if (!editableNow.value) {
    ElMessage.info('当前单据已生效，不能再确认或修改')
    return
  }
  let target = editingOrder.value
  if (isNewDraft.value || target === null) {
    target = await persistDraft(true)
    if (!target) return
  }
  await confirmTarget(target)
}

/** 编辑区「取消单据」：未落库的新草稿直接收起编辑区 */
async function handleCancelEditing(): Promise<void> {
  const target = editingOrder.value
  if (!target || isNewDraft.value) {
    closeEditor()
    return
  }
  await cancelTarget(target)
}

/** 列表行「确认」：仅草稿可确认 */
async function handleConfirmRow(row: Order): Promise<void> {
  if (row.status !== 'draft') {
    ElMessage.info('仅草稿状态可确认')
    return
  }
  await confirmTarget(row)
}

/** 列表行「取消」：仅草稿可取消 */
async function handleCancelRow(row: Order): Promise<void> {
  if (row.status !== 'draft') {
    ElMessage.info('仅草稿状态可取消')
    return
  }
  await cancelTarget(row)
}

// ---------- 已有单据列表 ----------

const orders = ref<Order[]>([])
const ordersLoading = ref(false)
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
/** 列表筛选：配送日（默认跟随顶部日期）+ 状态 */
const filterDate = ref<string>(requireDate.value)
const filterStatus = ref<OrderStatus | ''>('')

const ordersEmptyText = computed<string>(() =>
  activeStoreId.value === null ? '请先选择门店' : '该配送日暂无要货单，可获取 AI 建议或新建草稿'
)

async function loadOrders(): Promise<void> {
  if (activeStoreId.value === null) {
    orders.value = []
    total.value = 0
    return
  }
  ordersLoading.value = true
  try {
    const res = await listOrders({
      store_id: activeStoreId.value,
      require_date: filterDate.value || undefined,
      status: filterStatus.value || undefined,
      page: page.value,
      page_size: pageSize.value
    })
    orders.value = res.list
    total.value = res.total
  } catch {
    // request.ts 已弹错，这里保证回到空态而不是残留旧数据
    orders.value = []
    total.value = 0
  } finally {
    ordersLoading.value = false
  }
}

function handleSearch(): void {
  page.value = 1
  void loadOrders()
}

function handleReset(): void {
  filterDate.value = requireDate.value
  filterStatus.value = ''
  page.value = 1
  void loadOrders()
}

function handleCurrentChange(p: number): void {
  page.value = p
  void loadOrders()
}

function handleSizeChange(size: number): void {
  pageSize.value = size
  page.value = 1
  void loadOrders()
}

// 顶部日期变化：同步列表筛选并刷新；编辑区里若是别的配送日的单则收起
watch(requireDate, () => {
  filterDate.value = requireDate.value
  if (editingOrder.value && editingOrder.value.require_date !== requireDate.value) closeEditor()
  page.value = 1
  void loadOrders()
})

// 切换门店：编辑区一定是别家店的单，直接收起，避免改错门店的要货单
watch(activeStoreId, () => {
  closeEditor()
  page.value = 1
  void loadOrders()
})

onMounted(async () => {
  if (userStore.isLoggedIn && !userStore.user) {
    try {
      await userStore.fetchMe()
    } catch {
      // token 失效时 request.ts 已清 token 并跳登录页
    }
  }
  void loadSkuOptions()
  await loadStoreOptions()
  await loadOrders()
})
</script>

<template>
  <div class="page">
    <!-- 毛玻璃顶栏：品牌字 + 页面标题（V3 大字号 24px/800） -->
    <div class="page-head glass-nav">
      <h2><span class="brand-name">念家鲜饺</span>门店要货</h2>
      <div class="head-right">
        <span class="muted">当前门店：{{ storeLabel }}</span>
        <router-link to="/">← 返回首页</router-link>
      </div>
    </div>

    <!-- 条件区：配送日期 + 门店 + AI 建议入口 -->
    <el-card shadow="never" class="block">
      <div class="toolbar">
        <span class="label">配送日期</span>
        <el-date-picker
          v-model="requireDate"
          type="date"
          value-format="YYYY-MM-DD"
          :clearable="false"
          style="width: 170px"
        />
        <template v-if="boundStoreId === null">
          <span class="label">门店</span>
          <el-select
            v-model="selectedStoreId"
            filterable
            placeholder="请选择门店"
            :loading="storeLoading"
            style="width: 220px"
          >
            <el-option
              v-for="s in storeOptions"
              :key="s.id"
              :label="s.name + '（' + s.store_no + '）'"
              :value="s.id"
            />
          </el-select>
        </template>
        <el-tag v-else effect="plain" class="bound-tag">本店要货</el-tag>

        <el-button
          type="primary"
          :loading="suggestLoading"
          :disabled="activeStoreId === null"
          @click="handleSuggest"
        >
          获取 AI 建议
        </el-button>
        <el-button :disabled="activeStoreId === null || !canOrderWrite" @click="handleNewDraft">
          新建草稿
        </el-button>
      </div>
      <p class="tip">
        AI 建议仅生成草稿，需点「确认要货」才生效（确认后进入汇总流程）。
      </p>
    </el-card>

    <!-- AI 建议卡片区 -->
    <el-card shadow="never" class="block">
      <template #header>
        <div class="card-head">
          <span class="card-title">AI 要货建议</span>
          <span v-if="suggest" class="muted">
            快照 #{{ adviceId }}<template v-if="adviceModel"> · 策略 {{ adviceModel }}</template> ·
            采纳粒度：整份快照（按店按日）
            <el-tag v-if="adviceApplied" type="success" effect="light" size="small" class="gap-left">
              已采纳
            </el-tag>
          </span>
        </div>
      </template>

      <el-alert
        v-if="suggestError"
        type="error"
        :closable="false"
        show-icon
        title="建议生成失败"
        description="可能是后端未连通或当日无销量数据；可点击「获取 AI 建议」重试，或用「新建草稿」手工要货。"
      />

      <template v-else-if="suggest">
        <el-alert
          v-for="(w, wi) in adviceWarnings"
          :key="'warn-' + wi"
          type="info"
          :closable="false"
          show-icon
          :title="w"
          class="block-gap"
        />
        <p v-if="adviceBasis" class="suggest-summary">{{ adviceBasis }}</p>
        <div v-if="adviceItems.length > 0" class="suggest-grid">
          <div v-for="item in adviceItems" :key="item.sku_id" class="suggest-card">
            <div class="suggest-top">
              <span class="suggest-name">{{ item.sku_name || item.sku_no || 'SKU #' + item.sku_id }}</span>
              <el-tag v-if="item.nearest_expire_at" type="warning" effect="light" size="small">临期</el-tag>
            </div>
            <div class="suggest-qty">
              {{ numText(item.suggest_qty_unit) }}<span class="suggest-unit">{{ item.unit || '' }}</span>
            </div>
            <p class="suggest-reason">{{ item.reason || '依据：近 7 天要货量与总部仓可发量' }}</p>
            <p v-if="item.nearest_expire_at" class="suggest-expire">
              最近到期批次 {{ item.nearest_expire_at }}
            </p>
            <p v-if="item.hq_available_qty_base" class="suggest-stock">
              总部仓可发 {{ numText(item.hq_available_qty_base) }} {{ item.base_unit || '' }}
            </p>
            <div v-if="item.flags && item.flags.length > 0" class="suggest-flags">
              <el-tag v-for="f in item.flags" :key="f" type="warning" effect="plain" size="small">
                {{ f }}
              </el-tag>
            </div>
            <el-button
              type="primary"
              plain
              size="small"
              :loading="applyingSku === item.sku_id"
              :disabled="adviceApplied || !canApply"
              @click="handleApply(item)"
            >
              {{ adviceApplied ? '已生成草稿' : '应用' }}
            </el-button>
          </div>
        </div>
        <el-empty v-else :image-size="80" description="当日无需补充要货（建议明细为空）" />
        <p v-if="adviceSkippedCount > 0" class="tip">
          另有 {{ adviceSkippedCount }} 个 SKU 因总部仓无可发量未进入建议明细，可人工少量下单。
        </p>
      </template>

      <el-empty v-else :image-size="80" description="点上方「获取 AI 建议」，按本店销量/库存/效期生成要货建议" />
    </el-card>

    <!-- 草稿要货单编辑区 -->
    <el-card shadow="never" class="block">
      <template #header>
        <div class="card-head">
          <span class="card-title">草稿要货单</span>
          <span v-if="hasEditor" class="muted">
            {{ isNewDraft ? '未保存的新草稿' : editingNo }}
            <el-tag
              v-if="editingStatus"
              :type="orderStatusType(editingStatus)"
              effect="light"
              size="small"
              class="gap-left"
            >
              {{ orderStatusText(editingStatus) }}
            </el-tag>
            <span class="gap-left">配送日 {{ requireDate }}</span>
          </span>
        </div>
      </template>

      <template v-if="hasEditor">
        <el-alert
          v-if="!canOrderWrite"
          type="info"
          :closable="false"
          show-icon
          title="当前账号对要货单只读"
          description="缺少 order:create/update/confirm 权限点（§8.3 默认授予店长）；可查看明细，写操作请由店长账号完成。"
          class="block-gap"
        />
        <el-alert
          v-else-if="!editableNow"
          type="info"
          :closable="false"
          show-icon
          title="该单据已生效或已作废，明细只读"
          class="block-gap"
        />
        <el-alert
          v-if="skuOptions.length === 0 && !skuLoading"
          type="warning"
          :closable="false"
          show-icon
          title="SKU 列表未加载"
          description="无法选择商品；请确认后端 /skus 可用后刷新页面。"
          class="block-gap"
        />

        <el-table :data="draftRows" border class="draft-table">
          <el-table-column label="商品 SKU" min-width="280">
            <template #default="{ row }">
              <el-select
                v-model="row.sku_id"
                filterable
                clearable
                placeholder="选择商品"
                :disabled="!editableNow"
                style="width: 100%"
                @change="handleSkuChange(row as DraftRow)"
              >
                <el-option
                  v-for="sku in skuOptions"
                  :key="sku.id"
                  :label="sku.sku_no + ' ' + sku.name"
                  :value="sku.id"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="数量" width="170">
            <template #default="{ row }">
              <el-input-number
                v-model="row.qty_unit"
                :min="0"
                :precision="3"
                :step="1"
                :disabled="!editableNow"
                controls-position="right"
                style="width: 100%"
              />
            </template>
          </el-table-column>
          <el-table-column label="单位" width="220">
            <template #default="{ row }">
              <el-select v-model="row.unit" :disabled="!editableNow" placeholder="单位" style="width: 100%">
                <el-option
                  v-for="u in unitOptions(row as DraftRow)"
                  :key="u.value"
                  :label="u.label"
                  :value="u.value"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ $index }">
              <el-button link type="danger" :disabled="!editableNow" @click="removeRow($index)">删除</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty :image-size="80" description="还没有明细行，点下方「添加明细行」" />
          </template>
        </el-table>

        <div class="editor-actions">
          <el-button :disabled="!editableNow" @click="addRow">添加明细行</el-button>
          <el-button :loading="saving" :disabled="!editableNow" @click="persistDraft(false)">保存草稿</el-button>
          <el-button type="primary" :loading="saving" :disabled="!editableNow" @click="handleConfirmEditing">
            确认要货
          </el-button>
          <el-button
            type="danger"
            plain
            :loading="saving"
            :disabled="!editableNow || isNewDraft"
            @click="handleCancelEditing"
          >
            取消单据
          </el-button>
          <el-button link class="close-btn" @click="closeEditor">收起编辑区</el-button>
        </div>
      </template>

      <el-empty
        v-else
        :image-size="80"
        description="未在编辑任何单据：点列表里的「编辑」载入草稿，或点上方「新建草稿」"
      />
    </el-card>

    <!-- 已有单据列表 -->
    <el-card shadow="never" class="block">
      <template #header>
        <div class="card-head">
          <span class="card-title">要货单列表</span>
        </div>
      </template>

      <div class="toolbar">
        <el-date-picker
          v-model="filterDate"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="全部配送日"
          clearable
          style="width: 170px"
        />
        <el-select v-model="filterStatus" placeholder="全部状态" clearable style="width: 140px">
          <el-option label="草稿" value="draft" />
          <el-option label="已确认" value="confirmed" />
          <el-option label="已汇总" value="merged" />
          <el-option label="已取消" value="cancelled" />
        </el-select>
        <el-button type="primary" @click="handleSearch">查询</el-button>
        <el-button @click="handleReset">重置</el-button>
      </div>

      <el-table v-loading="ordersLoading" :data="orders" border>
        <el-table-column prop="order_no" label="单号" width="170" />
        <el-table-column prop="require_date" label="配送日" width="120" />
        <el-table-column label="来源" width="100">
          <template #default="{ row }">
            <el-tag :type="row.source === 'agent' ? 'success' : 'info'" effect="plain" size="small">
              {{ sourceText(row as Order) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="orderStatusType(row.status)" effect="light" size="small">
              {{ orderStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="明细行" width="100">
          <template #default="{ row }">
            {{ row.items && row.items.length > 0 ? row.items.length : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDraft(row as Order)">编辑</el-button>
            <el-button
              v-if="row.status === 'draft' && canOrderWrite"
              link
              type="success"
              @click="handleConfirmRow(row as Order)"
            >
              确认
            </el-button>
            <el-button
              v-if="row.status === 'draft' && canOrderWrite"
              link
              type="danger"
              @click="handleCancelRow(row as Order)"
            >
              取消
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :image-size="80" :description="ordersEmptyText" />
        </template>
      </el-table>

      <el-pagination
        class="pager"
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        background
        @current-change="handleCurrentChange"
        @size-change="handleSizeChange"
      />
    </el-card>
  </div>
</template>

<style scoped>
.page {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
}
/* 顶部毛玻璃导航条：.glass-nav 给半透明与模糊，这里管布局与圆角 */
.page-head {
  position: sticky;
  top: 12px;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 20px;
  padding: 16px 24px;
  border: 1px solid var(--nf-glass-border);
  border-radius: 16px;
}
/* 页面标题：24px / 800（docs/07 §3 大字号层级） */
.page-head h2 {
  margin: 0;
  font-size: 24px;
  font-weight: 800;
  color: var(--nf-ink);
  letter-spacing: 0.5px;
}
.brand-name {
  font-weight: 800;
  letter-spacing: 3px;
  margin-right: 14px;
  padding-right: 14px;
  color: var(--nf-deep);
  border-right: 1px solid rgba(26, 26, 26, 0.1);
}
.head-right {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 14px;
}
.page-head a {
  color: #6b6b6b;
  text-decoration: none;
  transition: color 0.2s;
}
.page-head a:hover {
  color: var(--nf-green);
}
.muted {
  color: var(--nf-muted);
  font-size: 13px;
}
/* 卡片化：16px 圆角 + 柔和阴影（主题已给 .el-card，这里补间距与去描边） */
.block {
  margin-bottom: 20px;
}
.block-gap {
  margin-bottom: 12px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.card-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--nf-ink);
}
.gap-left {
  margin-left: 8px;
}
.toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.label {
  font-size: 14px;
  color: #3c3c3c;
}
.tip {
  margin: 0;
  font-size: 13px;
  color: var(--nf-muted);
}
.bound-tag {
  --el-tag-bg-color: rgba(169, 217, 94, 0.18);
  --el-tag-border-color: rgba(62, 155, 71, 0.25);
  --el-tag-text-color: var(--nf-deep);
}
/* ---- AI 建议卡片：白底柔阴影 + hover 上浮 2px（Apple 式克制） ---- */
.suggest-summary {
  margin: 0 0 16px;
  padding: 14px 18px;
  border-radius: 12px;
  background: rgba(169, 217, 94, 0.14);
  color: var(--nf-deep);
  font-size: 14px;
}
.suggest-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 16px;
}
.suggest-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 18px;
  border-radius: 16px;
  background: #ffffff;
  border: 1px solid rgba(26, 26, 26, 0.06);
  box-shadow: var(--nf-shadow-card);
  transition: transform 0.2s ease, border-color 0.2s, box-shadow 0.2s;
}
.suggest-card:hover {
  transform: translateY(-2px);
  border-color: var(--nf-green);
  box-shadow: var(--nf-shadow-card-hover);
}
.suggest-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.suggest-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--nf-ink);
}
/* 建议数量：大字号品牌绿（本页视觉重点） */
.suggest-qty {
  font-size: 30px;
  font-weight: 800;
  line-height: 1.1;
  color: var(--nf-green);
}
.suggest-unit {
  margin-left: 6px;
  font-size: 14px;
  font-weight: 600;
  color: var(--nf-muted);
}
.suggest-reason {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: #6b6b6b;
}
.suggest-expire {
  margin: 0;
  font-size: 12px;
  color: #b7791f;
}
.suggest-stock {
  margin: 0;
  font-size: 12px;
  color: var(--nf-muted);
}
.suggest-flags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.suggest-card .el-button {
  align-self: flex-start;
  margin-top: 4px;
}
.draft-table {
  margin-bottom: 12px;
}
.editor-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.close-btn {
  margin-left: auto;
  color: #6b6b6b;
}
.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
</style>
