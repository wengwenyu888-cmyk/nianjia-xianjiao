<script setup lang="ts">
// 库存管理（docs/02 §7.2 批次库存 batch_stock + 批次流水 batch_flow；§8.2 库存端点，全部只读）
//   Tab1 批次库存 GET /stocks · Tab2 预警 GET /stocks/alerts · Tab3 流水 GET /stock-flows
// 可追溯 = 结存 + 流水双轨：结存表只存当前量，流水记每一笔变动（谁操作、依据哪张单）。
import { computed, onMounted, reactive, ref, watch } from 'vue'
import dayjs from 'dayjs'

import {
  getStockAlerts,
  listStockFlows,
  listStocks,
  type LowStockItem,
  type Stock,
  type StockAlerts,
  type StockFlow,
  type StockFlowType
} from '@/api/stock'
import { getSkus, getStores, type Sku, type Store } from '@/api/store'

// ---------- 格式化 ----------

/** 数量：最多 3 位小数（§7 DECIMAL(14,3)） */
function formatQty(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 3 })
}

/** 变动量：正数带 + 号，最多 3 位小数（加为正、减为负） */
function qtyChangeText(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return (n > 0 ? '+' : '') + n.toLocaleString('zh-CN', { maximumFractionDigits: 3 })
}

/** 时间戳：ISO8601 → YYYY-MM-DD HH:mm */
function formatDateTime(v: string | null | undefined): string {
  if (!v) return '—'
  const d = dayjs(v)
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm') : v
}

// ---------- 主数据字典（后端 Out 已带 store_name/sku_no/sku_name，缺失时才回退） ----------

const stores = ref<Store[]>([])
const skus = ref<Sku[]>([])
const storeMap = computed(() => new Map(stores.value.map((s) => [s.id, s])))
const skuMap = computed(() => new Map(skus.value.map((s) => [s.id, s])))

/** 门店展示：优先后端 store_name（0 = 总部仓），缺失回退本地字典 */
function storeName(id: number, name?: string | null): string {
  if (name) return name
  if (id === 0) return '总部仓'
  const hit = storeMap.value.get(id)
  return hit ? hit.name : '门店#' + id
}

/** SKU 展示：优先后端 sku_no/sku_name，缺失回退本地字典 */
function skuText(skuId: number, skuNo?: string | null, skuName?: string | null): string {
  const hit = skuMap.value.get(skuId)
  const no = skuNo || hit?.sku_no || 'SKU#' + skuId
  const name = skuName || hit?.name || ''
  return name ? no + ' ' + name : no
}

/**
 * 基础单位：结存 qty_base 一律基础单位口径，而 StockOut.unit 是订货/展示单位（sku.unit）。
 * 基础单位名取本地 SKU 字典；换算系数为 1 时两者同值，取不到字典时回退展示单位。
 */
function baseUnitOf(row: {
  sku_id: number
  unit?: string | null
  convert_factor?: number | null
}): string {
  const hit = skuMap.value.get(row.sku_id)
  if (hit?.base_unit) return hit.base_unit
  const factor =
    row.convert_factor === null || row.convert_factor === undefined ? 1 : Number(row.convert_factor)
  return factor === 1 ? row.unit || '—' : '—'
}

/** 展示单位数量 = 基础结存 ÷ 换算系数（换算系数 ≤1 时无意义，返回空串） */
function displayQtyText(row: Stock): string {
  const factor = Number(row.convert_factor ?? 1)
  if (!Number.isFinite(factor) || factor <= 1) return ''
  const qty = Number(row.qty_base || 0) / factor
  return '≈ ' + qty.toLocaleString('zh-CN', { maximumFractionDigits: 3 }) + ' ' + (row.unit || '')
}

async function loadDictionaries(): Promise<void> {
  const [storeRes, skuRes] = await Promise.allSettled([
    getStores({ page: 1, page_size: 200 }),
    getSkus({ page: 1, page_size: 200 })
  ])
  if (storeRes.status === 'fulfilled') stores.value = storeRes.value?.list ?? []
  if (skuRes.status === 'fulfilled') skus.value = skuRes.value?.list ?? []
}

// ---------- 剩余小时与临期判定（整行着色 / 状态标签共用） ----------

/** 临期阈值：≤24 小时红、≤72 小时橙（与预警接口默认 expire_hours=24 对齐） */
const EXPIRE_DANGER_HOURS = 24
const EXPIRE_WARN_HOURS = 72

/** 剩余小时：优先用后端 hours_to_expire，缺失时按 expire_at 现算（已过期为负） */
function hoursOf(row: Stock): number | null {
  if (row.hours_to_expire !== null && row.hours_to_expire !== undefined) {
    const n = Number(row.hours_to_expire)
    if (Number.isFinite(n)) return n
  }
  if (!row.expire_at) return null
  const d = dayjs(row.expire_at)
  return d.isValid() ? d.diff(dayjs(), 'hour') : null
}

/** 临期判定：后端 expiring 标记优先，缺失时按 ≤24 小时兜底 */
function isExpiring(row: Stock): boolean {
  if (typeof row.expiring === 'boolean') return row.expiring
  const h = hoursOf(row)
  return h !== null && h <= EXPIRE_DANGER_HOURS
}

/** 剩余小时展示：后端是 2 位小数的 Decimal，页面只保留 1 位（未过期带正号语义） */
function hoursText(h: number | null): string {
  if (h === null) return '—'
  const shown = Math.round(Math.abs(h) * 10) / 10
  if (h < 0) return '已过期 ' + shown + ' 小时'
  return shown + ' 小时'
}

/** 列表剩余小时（表格列） */
function remainHoursText(row: Stock): string {
  return hoursText(hoursOf(row))
}

/** 角标：临期卡片右上角红标（已过期 / 剩余整点小时，保持短小） */
function hoursBadge(row: Stock): string {
  const h = hoursOf(row)
  if (h === null) return '无到期日'
  if (h < 0) return '已过期'
  return Math.max(0, Math.round(h)) + 'h'
}

function stockStatusText(row: Stock): string {
  const h = hoursOf(row)
  if (h === null) return '无到期日'
  if (h < 0) return '已过期'
  if (h <= EXPIRE_DANGER_HOURS) return '临期'
  if (h <= EXPIRE_WARN_HOURS) return '临近'
  return '正常'
}

function stockStatusTag(row: Stock): 'info' | 'danger' | 'warning' | 'success' {
  const h = hoursOf(row)
  if (h === null) return 'info'
  if (h < 0) return 'danger'
  if (h <= EXPIRE_DANGER_HOURS) return 'danger'
  if (h <= EXPIRE_WARN_HOURS) return 'warning'
  return 'success'
}

/** 整行着色：≤24h 红、≤72h 橙（Element 行背景需覆盖 td.el-table__cell 才可见） */
function stockRowClass({ row }: { row: Stock }): string {
  const h = hoursOf(row)
  if (h === null) return ''
  if (h <= EXPIRE_DANGER_HOURS) return 'row-expire-danger'
  if (h <= EXPIRE_WARN_HOURS) return 'row-expire-warn'
  return ''
}

// ---------- Tab 状态 ----------

type TabName = 'stock' | 'alerts' | 'flow'
const activeTab = ref<TabName>('stock')

// ---------- Tab1 批次库存（GET /stocks） ----------

const loading = ref(false)
const list = ref<Stock[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

const query = reactive<{
  store_id: number | undefined
  sku_id: number | undefined
  batch_no: string
  expire_within_hours: number | null
  include_zero: boolean
}>({
  store_id: undefined,
  sku_id: undefined,
  batch_no: '',
  expire_within_hours: null,
  include_zero: false
})

/** 概览卡（当前页聚合；§8.2 未提供库存汇总端点，故只做页内口径并显式标注） */
const stockStats = computed(() => {
  const rows = list.value
  const expiring = rows.filter((r) => isExpiring(r)).length
  const qty = rows.reduce((sum, r) => sum + Number(r.qty_base || 0), 0)
  // 临期口径 = 后端 expiring 标记：未传临期小时时后端按 24 小时判定
  const threshold = query.expire_within_hours ?? EXPIRE_DANGER_HOURS
  return [
    { label: '批次数（当前页）', value: String(rows.length) },
    { label: '临期批次（≤' + threshold + 'h）', value: String(expiring) },
    { label: '总库存（基础单位）', value: formatQty(qty) }
  ]
})

async function fetchStocks(): Promise<void> {
  loading.value = true
  try {
    const res = await listStocks({
      page: page.value,
      page_size: pageSize.value,
      store_id: query.store_id,
      sku_id: query.sku_id,
      batch_no: query.batch_no.trim() || undefined,
      expire_within_hours: query.expire_within_hours ?? undefined,
      include_zero: query.include_zero || undefined
    })
    list.value = res?.list ?? []
    total.value = res?.total ?? 0
  } catch {
    // request.ts 已统一提示错误；置空保证页面可用
    list.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function handleSearch(): void {
  page.value = 1
  void fetchStocks()
}

function handleReset(): void {
  query.store_id = undefined
  query.sku_id = undefined
  query.batch_no = ''
  query.expire_within_hours = null
  query.include_zero = false
  handleSearch()
}

function handleCurrentChange(p: number): void {
  page.value = p
  void fetchStocks()
}

function handleSizeChange(size: number): void {
  pageSize.value = size
  page.value = 1
  void fetchStocks()
}

// ---------- Tab2 临期与低库存预警（GET /stocks/alerts） ----------

const alertLoading = ref(false)
const alertsLoaded = ref(false)
const alerts = ref<StockAlerts | null>(null)

/**
 * 预警筛选：门店 + 临期小时（默认 24）+ 低库存阈值（默认 20，可在右栏调整后重新查询）。
 * 数据范围口径：后端 /stocks/alerts 缺省即总部仓（store_id=0），一次只覆盖一个范围，
 * 故默认 0 且不提供「全部门店」选项，避免页面口径与后端错位。
 */
const alertStoreId = ref<number>(0)
const expireHours = ref<number>(24)
const lowQtyBase = ref<number>(20)
const alertLimit = ref<number>(50)

/** 临期批次：按剩余小时升序（快过期的排前面） */
const expiringList = computed<Stock[]>(() => {
  const rows = (alerts.value?.expiring ?? []).slice()
  rows.sort((a, b) => (hoursOf(a) ?? Number.MAX_SAFE_INTEGER) - (hoursOf(b) ?? Number.MAX_SAFE_INTEGER))
  return rows
})

const lowStockList = computed<LowStockItem[]>(() => alerts.value?.low_stock ?? [])
const alertSummary = computed(() => alerts.value?.summary ?? null)

/** 展示条数 / 命中总数：后端 summary 计数不受 limit 截断（已展示 N / 共 M） */
const expiringCountText = computed<string>(() => {
  const shown = expiringList.value.length
  const hit = alertSummary.value?.expiring_count
  return hit === undefined ? '共 ' + shown + ' 批' : '已展示 ' + shown + ' / 共 ' + hit + ' 批'
})
const lowStockCountText = computed<string>(() => {
  const shown = lowStockList.value.length
  const hit = alertSummary.value?.low_stock_count
  return hit === undefined ? '共 ' + shown + ' 个' : '已展示 ' + shown + ' / 共 ' + hit + ' 个'
})

async function fetchAlerts(): Promise<void> {
  alertLoading.value = true
  try {
    alerts.value = await getStockAlerts({
      store_id: alertStoreId.value,
      expire_hours: expireHours.value,
      low_qty_base: lowQtyBase.value,
      limit: alertLimit.value
    })
  } catch {
    alerts.value = null
  } finally {
    alertsLoaded.value = true
    alertLoading.value = false
  }
}

// ---------- Tab3 批次流水（GET /stock-flows） ----------

const FLOW_TYPES: {
  value: StockFlowType
  label: string
  tag: 'success' | 'warning' | 'danger' | 'info'
}[] = [
  { value: 'receive_add', label: '收货入库', tag: 'success' },
  { value: 'pick_sub', label: '分拣出库', tag: 'warning' },
  { value: 'loss_sub', label: '报损扣减', tag: 'danger' },
  { value: 'count_adjust', label: '盘点调整', tag: 'info' }
]

/** 关联单据类型文案（batch_flow.doc_type） */
const DOC_TYPE_LABELS: Record<string, string> = {
  purchase_order: '采购单',
  pick: '分拣单',
  loss: '报损单',
  stock_count: '盘点单',
  other: '其他'
}

function flowTypeText(v: StockFlowType | string): string {
  return FLOW_TYPES.find((it) => it.value === v)?.label ?? v
}

function flowTypeTag(v: StockFlowType | string): 'success' | 'warning' | 'danger' | 'info' {
  return FLOW_TYPES.find((it) => it.value === v)?.tag ?? 'info'
}

function docText(row: StockFlow): string {
  const label = DOC_TYPE_LABELS[row.doc_type] ?? row.doc_type
  return row.doc_no ? label + ' ' + row.doc_no : label
}

const flowLoading = ref(false)
const flowLoaded = ref(false)
const flows = ref<StockFlow[]>([])
const flowTotal = ref(0)
const flowPage = ref(1)
const flowPageSize = ref(20)

const flowQuery = reactive<{
  store_id: number | undefined
  sku_id: number | undefined
  batch_no: string
  flow_type: StockFlowType | ''
}>({
  store_id: undefined,
  sku_id: undefined,
  batch_no: '',
  flow_type: ''
})

async function fetchFlows(): Promise<void> {
  flowLoading.value = true
  try {
    const res = await listStockFlows({
      page: flowPage.value,
      page_size: flowPageSize.value,
      store_id: flowQuery.store_id,
      sku_id: flowQuery.sku_id,
      batch_no: flowQuery.batch_no.trim() || undefined,
      flow_type: flowQuery.flow_type || undefined
    })
    flows.value = res?.list ?? []
    flowTotal.value = res?.total ?? 0
  } catch {
    flows.value = []
    flowTotal.value = 0
  } finally {
    flowLoaded.value = true
    flowLoading.value = false
  }
}

function handleFlowSearch(): void {
  flowPage.value = 1
  void fetchFlows()
}

function handleFlowReset(): void {
  flowQuery.store_id = undefined
  flowQuery.sku_id = undefined
  flowQuery.batch_no = ''
  flowQuery.flow_type = ''
  handleFlowSearch()
}

function handleFlowCurrentChange(p: number): void {
  flowPage.value = p
  void fetchFlows()
}

function handleFlowSizeChange(size: number): void {
  flowPageSize.value = size
  flowPage.value = 1
  void fetchFlows()
}

// ---------- 生命周期：字典 + Tab1；预警与流水首次进入对应 Tab 才请求 ----------

onMounted(async () => {
  await loadDictionaries()
  await fetchStocks()
})

watch(activeTab, (tab) => {
  if (tab === 'alerts' && !alertsLoaded.value) void fetchAlerts()
  if (tab === 'flow' && !flowLoaded.value) void fetchFlows()
})
</script>

<template>
  <div class="page">
    <div class="page-head glass-nav">
      <h2><span class="brand-name">念家鲜饺</span>库存管理</h2>
      <router-link to="/">← 返回首页</router-link>
    </div>

    <el-card shadow="never">
      <el-tabs v-model="activeTab">
        <!-- ===== Tab1 批次库存 ===== -->
        <el-tab-pane label="批次库存" name="stock">
          <div class="stat-row">
            <div v-for="s in stockStats" :key="s.label" class="stat-card">
              <div class="stat-label">{{ s.label }}</div>
              <div class="stat-value">{{ s.value }}</div>
            </div>
          </div>

          <div class="toolbar">
            <span class="label">门店</span>
            <el-select
              v-model="query.store_id"
              placeholder="全部门店与总部仓"
              clearable
              filterable
              style="width: 200px"
            >
              <!-- store_id=0 即总部仓（batch_stock 约定） -->
              <el-option label="总部仓" :value="0" />
              <el-option
                v-for="s in stores"
                :key="s.id"
                :label="s.name + '（' + s.store_no + '）'"
                :value="s.id"
              />
            </el-select>
            <span class="label">SKU</span>
            <el-select
              v-model="query.sku_id"
              placeholder="全部 SKU"
              clearable
              filterable
              style="width: 220px"
            >
              <el-option
                v-for="s in skus"
                :key="s.id"
                :label="s.sku_no + ' ' + s.name"
                :value="s.id"
              />
            </el-select>
            <span class="label">批次号</span>
            <el-input
              v-model="query.batch_no"
              placeholder="如 B20261013-01"
              clearable
              style="width: 180px"
              @keyup.enter="handleSearch"
            />
            <span class="label">临期小时</span>
            <el-input-number
              v-model="query.expire_within_hours"
              :min="1"
              :precision="0"
              :step="12"
              placeholder="如 72"
              style="width: 120px"
            />
            <el-switch v-model="query.include_zero" active-text="含零库存" />
            <el-button type="primary" @click="handleSearch">查询</el-button>
            <el-button @click="handleReset">重置</el-button>
          </div>
          <p class="tip">
            剩余小时 ≤24 整行标红、≤72 整行标橙（已过期为负值，同标红）；结存数量一律按基础单位。
          </p>

          <el-table v-loading="loading" :data="list" border stripe :row-class-name="stockRowClass">
            <el-table-column label="门店" min-width="150">
              <template #default="{ row }">{{ storeName(row.store_id, row.store_name) }}</template>
            </el-table-column>
            <el-table-column label="SKU" min-width="200">
              <template #default="{ row }">{{ skuText(row.sku_id, row.sku_no, row.sku_name) }}</template>
            </el-table-column>
            <el-table-column prop="batch_no" label="批次号" width="170" />
            <el-table-column label="结存" width="170" align="right">
              <template #default="{ row }">
                {{ formatQty(row.qty_base) }}
                <span v-if="displayQtyText(row as Stock)" class="muted">
                  {{ displayQtyText(row as Stock) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="单位(基础)" width="110" align="center">
              <template #default="{ row }">{{ baseUnitOf(row as Stock) }}</template>
            </el-table-column>
            <el-table-column label="保质期至" width="160">
              <template #default="{ row }">{{ formatDateTime(row.expire_at) }}</template>
            </el-table-column>
            <el-table-column label="剩余小时" width="140" align="right">
              <!-- 插槽 row 为 DefaultRow，涉及整行参数的调用一律显式收窄 -->
              <template #default="{ row }">{{ remainHoursText(row as Stock) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="stockStatusTag(row as Stock)" effect="light">
                  {{ stockStatusText(row as Stock) }}
                </el-tag>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty :image-size="80" description="暂无批次库存：可在采购管理收货入库生成批次" />
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
        </el-tab-pane>

        <!-- ===== Tab2 临期与低库存预警 ===== -->
        <el-tab-pane label="临期与低库存预警" name="alerts">
          <div class="toolbar">
            <span class="label">门店</span>
            <el-select v-model="alertStoreId" filterable style="width: 200px">
              <!-- 预警一次只看一个范围，缺省即总部仓，故不提供「全部」 -->
              <el-option label="总部仓" :value="0" />
              <el-option
                v-for="s in stores"
                :key="s.id"
                :label="s.name + '（' + s.store_no + '）'"
                :value="s.id"
              />
            </el-select>
            <span class="label">临期小时</span>
            <el-input-number
              v-model="expireHours"
              :min="1"
              :precision="0"
              :step="12"
              style="width: 120px"
            />
            <el-button type="primary" :loading="alertLoading" @click="fetchAlerts">查询预警</el-button>
          </div>
          <p class="tip">
            <template v-if="alertSummary">
              统计时点 {{ formatDateTime(alertSummary.as_of) }} · 临期阈值
              {{ alertSummary.expire_hours }} 小时 · 低库存阈值
              {{ formatQty(alertSummary.low_qty_base) }}（基础单位）· 临期
              {{ alertSummary.expiring_count }} 批 / 低库存 {{ alertSummary.low_stock_count }} 个
            </template>
            <template v-else>预警数据未加载：点「查询预警」按当前门店与阈值拉取</template>
          </p>
          <p class="tip">
            数据范围为所选门店（总部仓 store_id=0，也是后端缺省口径）；两条清单各受 limit=50 约束，
            命中总数以汇总行「临期 / 低库存」为准。
          </p>

          <div class="alert-grid">
            <!-- 左：临期批次（升序 + 红色角标） -->
            <section class="alert-col">
              <div class="alert-col-head">
                <span class="sub-title">临期批次</span>
                <span class="muted">按剩余小时升序 · {{ expiringCountText }}</span>
              </div>
              <div v-loading="alertLoading" class="alert-list">
                <div v-for="b in expiringList" :key="'exp-' + b.id" class="alert-card">
                  <div class="alert-card-head">
                    <span class="batch-no">{{ b.batch_no }}</span>
                    <el-badge :value="hoursBadge(b)" type="danger" class="expire-badge" />
                  </div>
                  <div class="alert-card-line">{{ skuText(b.sku_id, b.sku_no, b.sku_name) }}</div>
                  <div class="alert-card-line muted">
                    {{ storeName(b.store_id, b.store_name) }} · 结存 {{ formatQty(b.qty_base) }}
                    {{ baseUnitOf(b) }}
                  </div>
                  <div class="alert-card-line muted">
                    保质期至 {{ formatDateTime(b.expire_at) }} · 剩余 {{ remainHoursText(b) }}
                  </div>
                </div>
                <el-empty
                  v-if="!alertLoading && expiringList.length === 0"
                  :image-size="70"
                  description="没有命中临期阈值的批次"
                />
              </div>
            </section>

            <!-- 右：低库存 SKU（阈值可调 + 重新查询） -->
            <section class="alert-col">
              <div class="alert-col-head">
                <span class="sub-title">低库存 SKU · <span class="muted">{{ lowStockCountText }}</span></span>
                <span class="alert-controls">
                  <span class="label">阈值</span>
                  <el-input-number
                    v-model="lowQtyBase"
                    :min="0"
                    :precision="3"
                    :step="5"
                    size="small"
                    style="width: 130px"
                  />
                  <el-button
                    size="small"
                    type="primary"
                    plain
                    :loading="alertLoading"
                    @click="fetchAlerts"
                  >
                    重新查询
                  </el-button>
                </span>
              </div>
              <div v-loading="alertLoading" class="alert-list">
                <div v-for="s in lowStockList" :key="'low-' + s.sku_id" class="alert-card">
                  <div class="alert-card-head">
                    <span class="batch-no">{{ skuText(s.sku_id, s.sku_no, s.sku_name) }}</span>
                    <el-tag type="warning" effect="light" size="small">低于阈值</el-tag>
                  </div>
                  <div class="alert-card-line">
                    合计结存 {{ formatQty(s.qty_base) }} {{ baseUnitOf(s) }} · 阈值
                    {{ formatQty(s.threshold) }}
                  </div>
                  <div class="alert-card-line muted">
                    涉及 {{ s.batch_count === null || s.batch_count === undefined ? '—' : s.batch_count }}
                    个批次
                  </div>
                </div>
                <el-empty
                  v-if="!alertLoading && lowStockList.length === 0"
                  :image-size="70"
                  description="没有低于阈值的 SKU"
                />
              </div>
            </section>
          </div>
        </el-tab-pane>

        <!-- ===== Tab3 批次流水 ===== -->
        <el-tab-pane label="批次流水" name="flow">
          <div class="toolbar">
            <span class="label">门店</span>
            <el-select
              v-model="flowQuery.store_id"
              placeholder="全部门店与总部仓"
              clearable
              filterable
              style="width: 200px"
            >
              <!-- store_id=0 即总部仓（batch_flow 约定） -->
              <el-option label="总部仓" :value="0" />
              <el-option
                v-for="s in stores"
                :key="s.id"
                :label="s.name + '（' + s.store_no + '）'"
                :value="s.id"
              />
            </el-select>
            <span class="label">SKU</span>
            <el-select
              v-model="flowQuery.sku_id"
              placeholder="全部 SKU"
              clearable
              filterable
              style="width: 220px"
            >
              <el-option
                v-for="s in skus"
                :key="s.id"
                :label="s.sku_no + ' ' + s.name"
                :value="s.id"
              />
            </el-select>
            <span class="label">批次号</span>
            <el-input
              v-model="flowQuery.batch_no"
              placeholder="如 B20261013-01"
              clearable
              style="width: 170px"
              @keyup.enter="handleFlowSearch"
            />
            <span class="label">流水类型</span>
            <el-select v-model="flowQuery.flow_type" placeholder="全部类型" clearable style="width: 150px">
              <el-option v-for="it in FLOW_TYPES" :key="it.value" :label="it.label" :value="it.value" />
            </el-select>
            <el-button type="primary" @click="handleFlowSearch">查询</el-button>
            <el-button @click="handleFlowReset">重置</el-button>
          </div>
          <p class="tip">
            流水为只追加台账：每笔变动记「谁操作、依据哪张单」，与结存表逐笔对账（记错只能写反向冲正流水）。
          </p>

          <el-table v-loading="flowLoading" :data="flows" border stripe>
            <el-table-column label="时间" width="160">
              <template #default="{ row }">{{ formatDateTime(row.occurred_at) }}</template>
            </el-table-column>
            <el-table-column label="类型" width="120">
              <template #default="{ row }">
                <el-tag :type="flowTypeTag(row.flow_type)" effect="light">
                  {{ flowTypeText(row.flow_type) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="batch_no" label="批次号" width="170" />
            <el-table-column label="SKU" min-width="200">
              <template #default="{ row }">{{ skuText(row.sku_id, row.sku_no, row.sku_name) }}</template>
            </el-table-column>
            <el-table-column label="变动数量" width="130" align="right">
              <template #default="{ row }">
                <span :class="{ 'danger-text': Number(row.qty_change_base) < 0 }">
                  {{ qtyChangeText(row.qty_change_base) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="变动后结存" width="130" align="right">
              <template #default="{ row }">{{ formatQty(row.qty_after_base) }}</template>
            </el-table-column>
            <el-table-column label="关联单据" min-width="200">
              <template #default="{ row }">{{ docText(row as StockFlow) }}</template>
            </el-table-column>
            <el-table-column label="操作人" width="110">
              <template #default="{ row }">
                <span class="muted">用户#{{ row.operate_by }}</span>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty :image-size="80" description="暂无批次流水：收货 / 分拣 / 报损 / 盘点都会在此记一笔" />
            </template>
          </el-table>

          <el-pagination
            class="pager"
            v-model:current-page="flowPage"
            v-model:page-size="flowPageSize"
            :total="flowTotal"
            :page-sizes="[10, 20, 50, 100]"
            layout="total, sizes, prev, pager, next, jumper"
            background
            @current-change="handleFlowCurrentChange"
            @size-change="handleFlowSizeChange"
          />
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<style scoped>
.page {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
}
/* 顶栏：毛玻璃白底（Apple 式克制，V3 规范） */
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
.page-head a {
  color: #6b6b6b;
  text-decoration: none;
  font-size: 14px;
  transition: color 0.2s;
}
.page-head a:hover {
  color: var(--nf-green);
}
.page :deep(.el-card) {
  border: none;
  border-radius: 16px;
  box-shadow: var(--nf-shadow-card);
  background: #ffffff;
}
/* 概览卡片：白卡 + 16px 圆角 + 柔和阴影，大数字留白 */
.stat-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 18px;
}
.stat-card {
  padding: 20px 22px;
  background: #ffffff;
  border-radius: 16px;
  box-shadow: var(--nf-shadow-card);
}
.stat-label {
  font-size: 13px;
  color: var(--nf-muted);
}
.stat-value {
  margin-top: 6px;
  font-size: 28px;
  font-weight: 800;
  color: var(--nf-ink);
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.label {
  font-size: 14px;
  color: #3c3c3c;
}
.tip {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--nf-muted);
}
.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
.muted {
  color: var(--nf-muted);
  font-size: 13px;
}
/* 变动量为负（分拣减 / 报损减）：品牌橙红告警色 */
.danger-text {
  color: #e2604a;
  font-weight: 600;
}
/* 整行着色：≤24h 红、≤72h 橙（与 docs/07 告警色一致，克制使用浅底） */
.page :deep(.el-table .row-expire-danger td.el-table__cell) {
  background: rgba(226, 96, 74, 0.08);
  color: #e2604a;
}
.page :deep(.el-table .row-expire-warn td.el-table__cell) {
  background: rgba(240, 180, 41, 0.14);
  color: #b7791f;
}
/* ---- Tab2 预警：左右两栏卡片列表 ---- */
.alert-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}
.alert-col {
  min-width: 0;
}
.alert-col-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.alert-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}
.sub-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--nf-ink);
}
/* 卡片列表：奶油白浅底 + 12px 圆角，滚动区限高避免长列表顶开页面 */
.alert-list {
  display: grid;
  gap: 12px;
  max-height: 560px;
  overflow-y: auto;
  padding: 12px;
  border-radius: 16px;
  background: #fbf8f0;
}
.alert-card {
  padding: 14px 16px;
  background: #ffffff;
  border-radius: 12px;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.05);
}
.alert-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-height: 22px;
  margin-bottom: 8px;
}
.batch-no {
  font-size: 15px;
  font-weight: 700;
  color: var(--nf-deep);
  word-break: break-all;
}
/* el-badge 角标：红色剩余小时标记，右侧留出角标空间 */
.expire-badge {
  margin-right: 8px;
  flex: 0 0 auto;
}
.alert-card-line {
  font-size: 13px;
  color: var(--nf-ink);
  line-height: 1.7;
}
.alert-card-line.muted {
  color: var(--nf-muted);
}
@media (max-width: 900px) {
  .page {
    padding: 16px;
  }
  .stat-row {
    grid-template-columns: 1fr;
  }
  .alert-grid {
    grid-template-columns: 1fr;
  }
}
</style>
