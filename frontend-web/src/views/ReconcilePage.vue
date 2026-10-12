<script setup lang="ts">
// 对账与 KPI：对账单（周期生成 / 查询 / 确认）+ 门店 KPI（盈亏核算 + 损耗率/要货准确率/周转）
// 接口（§8.2 对账核算，路径与方法逐字对齐）：
//   POST /reconciles/generate · GET /reconciles?period=&store_id= · POST /reconciles/{id}/confirm
//   GET /stores/{id}/profit?period= · GET /stores/{id}/kpi?period=
import { computed, onMounted, ref } from 'vue'
import dayjs from 'dayjs'
import isoWeek from 'dayjs/plugin/isoWeek'
import { ElMessage } from 'element-plus'

import {
  confirmReconcile,
  generateReconcile,
  getStoreKpi,
  getStoreProfit,
  listReconciles,
  newIdempotencyKey,
  type Reconcile,
  type ReconcileStatus,
  type StoreProfit
} from '@/api/settlement'
import { getStores, type Store } from '@/api/store'
import { useUserStore } from '@/stores/user'

// ISO 周支持：§7.5 reconcile.period 形如 2026-W42
dayjs.extend(isoWeek)

const userStore = useUserStore()

/** 权限：生成与确认对账均限 admin（§8.2 对账核算默认角色 / §8.3 reconcile:generate、reconcile:confirm） */
const canGenerate = computed(() => userStore.roleCodes.includes('admin'))
const canConfirm = computed(() => userStore.roleCodes.includes('admin'))

/** 对账周期口径 2026-W42：由所选周内任一天的日期换算 ISO 周 */
function toPeriod(date: string): string {
  const d = dayjs(date)
  if (!d.isValid()) return ''
  return d.isoWeekYear() + '-W' + String(d.isoWeek()).padStart(2, '0')
}

// ---- 格式化 ----
/** 金额：两位小数 + 千分位（后端 DECIMAL 可能下发字符串，统一 Number 归一） */
function formatMoney(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return '¥' + n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** 差异额：带正负号（正=外部台账多出，负=实际少收） */
function formatDiff(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return (n > 0 ? '+' : '') + '¥' + n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** 时间戳：ISO8601 → YYYY-MM-DD HH:mm（§8.1 时间约定） */
function formatDateTime(v: string | null | undefined): string {
  if (!v) return '—'
  const d = dayjs(v)
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm') : v
}

/** 百分比：1 位小数 */
function formatPercent(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toFixed(1) + '%'
}

/** 天数：1 位小数 */
function formatDays(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toFixed(1) + ' 天'
}

/** 对账单状态文案与配色（§7.5 reconcile.status） */
const reconcileStatusOptions: {
  value: ReconcileStatus
  label: string
  tag: 'info' | 'success' | 'warning'
}[] = [
  { value: 'draft', label: '待确认', tag: 'warning' },
  { value: 'confirmed', label: '已确认', tag: 'success' },
  { value: 'done', label: '已归档', tag: 'info' }
]

function reconcileStatusText(v: ReconcileStatus): string {
  return reconcileStatusOptions.find((it) => it.value === v)?.label ?? v
}

function reconcileStatusTag(v: ReconcileStatus): 'info' | 'success' | 'warning' {
  return reconcileStatusOptions.find((it) => it.value === v)?.tag ?? 'info'
}

/** el-table 插槽 row 为 DefaultRow，传给具体类型处理函数前显式收窄 */
function asReconcile(row: unknown): Reconcile {
  return row as Reconcile
}

/** 应配金额 = 本周期内部结算额（§7.5 reconcile.total_amount） */
function payableOf(row: Reconcile): number {
  return Number(row.total_amount || 0)
}

/** 实收金额 = 内部结算额 - 与管家婆差异额（§7.5 只有 total_amount / diff_amount 两列金额） */
function receivedOf(row: Reconcile): number {
  return payableOf(row) - Number(row.diff_amount || 0)
}

// ---- 主数据映射 ----
const stores = ref<Store[]>([])
const storeMap = computed(() => new Map(stores.value.map((s) => [s.id, s])))

function storeName(id: number): string {
  const s = storeMap.value.get(id)
  return s ? s.name : '门店#' + id
}

// ---- Tab 状态 ----
const activeTab = ref<'bill' | 'kpi'>('bill')

// ---- Tab 1：对账单 ----
/** 所选周内任一天，换算为 ISO 周作为对账周期 */
const billPeriodDate = ref<string>(dayjs().format('YYYY-MM-DD'))
const billPeriod = computed(() => toPeriod(billPeriodDate.value))

const billLoading = ref(false)
const bills = ref<Reconcile[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const billFilterStoreId = ref<number | undefined>(undefined)

/** 当前页对账合计概览（§8.2 未提供汇总端点，故按页聚合） */
const billStats = computed(() => {
  let payable = 0
  let received = 0
  let diff = 0
  bills.value.forEach((row) => {
    payable += payableOf(row)
    received += receivedOf(row)
    diff += Number(row.diff_amount || 0)
  })
  return [
    { label: '应配金额合计', value: formatMoney(payable) },
    { label: '实收金额合计', value: formatMoney(received) },
    { label: '差异合计', value: formatDiff(diff) },
    { label: '对账单数（当前页）', value: String(bills.value.length) }
  ]
})

async function fetchBills(): Promise<void> {
  billLoading.value = true
  try {
    const res = await listReconciles({
      page: page.value,
      page_size: pageSize.value,
      period: billPeriod.value || undefined,
      store_id: billFilterStoreId.value
    })
    bills.value = res?.list ?? []
    total.value = res?.total ?? 0
  } catch {
    // request.ts 已统一提示错误
    bills.value = []
    total.value = 0
  } finally {
    billLoading.value = false
  }
}

function handleSearchBills(): void {
  page.value = 1
  void fetchBills()
}

function handleResetBills(): void {
  billPeriodDate.value = dayjs().format('YYYY-MM-DD')
  billFilterStoreId.value = undefined
  handleSearchBills()
}

function handleCurrentChange(p: number): void {
  page.value = p
  void fetchBills()
}

function handleSizeChange(size: number): void {
  pageSize.value = size
  page.value = 1
  void fetchBills()
}

// ---- 生成对账单（POST /reconciles/generate） ----
const genVisible = ref(false)
const generating = ref(false)
const genKey = ref(newIdempotencyKey())
/** 生成目标门店：留空表示按周期生成全部门店 */
const genStoreId = ref<number | undefined>(undefined)

function openGenerate(): void {
  genStoreId.value = undefined
  genKey.value = newIdempotencyKey()
  genVisible.value = true
}

async function submitGenerate(): Promise<void> {
  if (!billPeriod.value) {
    ElMessage.warning('请先选择对账周期')
    return
  }
  generating.value = true
  try {
    await generateReconcile({ period: billPeriod.value, store_id: genStoreId.value }, genKey.value)
    ElMessage.success('对账单生成完成：' + billPeriod.value)
    genKey.value = newIdempotencyKey()
    genVisible.value = false
    await fetchBills()
  } catch {
    // request.ts 已统一提示（周期已存在时后端按 uk_store_period 返回 40900）
  } finally {
    generating.value = false
  }
}

// ---- 确认对账（POST /reconciles/{id}/confirm） ----
const confirmVisible = ref(false)
const confirming = ref(false)
const confirmTarget = ref<Reconcile | null>(null)
/** 与管家婆的差异额，默认取对账单当前差异值 */
const confirmDiff = ref<number>(0)

function openConfirm(row: Reconcile): void {
  if (!canConfirm.value) {
    ElMessage.warning('确认对账需要管理员权限（权限点 reconcile:confirm）')
    return
  }
  confirmTarget.value = row
  confirmDiff.value = Number(row.diff_amount || 0)
  confirmVisible.value = true
}

async function submitConfirm(): Promise<void> {
  const target = confirmTarget.value
  if (!target) return
  const diff = Number(confirmDiff.value)
  if (Number.isNaN(diff)) {
    ElMessage.warning('差异额需为数字')
    return
  }
  confirming.value = true
  try {
    await confirmReconcile(target.id, { diff_amount: diff })
    ElMessage.success('对账单已确认：' + (target.store_name || storeName(target.store_id)))
    confirmVisible.value = false
    await fetchBills()
  } catch {
    // request.ts 已统一提示
  } finally {
    confirming.value = false
  }
}

// ---- Tab 2：门店 KPI ----
interface KpiRow {
  store_id: number
  store_name: string
  revenue: number
  gross_profit: number
  gross_margin: number
  loss_rate: number
  order_accuracy: number
  turnover_days: number
}

/** 损耗率告警阈值：> 3% 整行标红（原型评审口径，对应 docs/01 损耗率 KPI） */
const LOSS_RATE_WARN = 3

const kpiStoreId = ref<number | undefined>(undefined)
const kpiPeriodDate = ref<string>(dayjs().format('YYYY-MM-DD'))
const kpiPeriod = computed(() => toPeriod(kpiPeriodDate.value))
const kpiLoading = ref(false)
const kpiRows = ref<KpiRow[]>([])
const kpiFails = ref(0)
const kpiQueried = ref(false)
/** 单店查询时的盈亏明细（GET /stores/{id}/profit） */
const profitDetail = ref<StoreProfit | null>(null)

/**
 * 兼容读取数值字段：§8.2 只约定端点与用途，未固定响应字段名，
 * 这里对常见别名做容错；后端定稿后只需在此补齐或收敛别名。
 */
function readNum(src: unknown, keys: string[]): number {
  if (!src || typeof src !== 'object') return 0
  const obj = src as Record<string, unknown>
  for (const k of keys) {
    const v = obj[k]
    if (v === null || v === undefined || v === '') continue
    const n = Number(v)
    if (!Number.isNaN(n)) return n
  }
  return 0
}

const REVENUE_KEYS = ['revenue', 'revenue_amount', 'sales_amount', 'turnover_amount']
const GROSS_KEYS = ['gross_profit', 'grossProfit', 'gross']
const MARGIN_KEYS = ['gross_margin', 'grossMargin', 'margin']
const LOSS_RATE_KEYS = ['loss_rate', 'lossRate', 'loss_ratio']
const ACCURACY_KEYS = ['order_accuracy', 'orderAccuracy', 'accuracy', 'order_accuracy_rate']
const TURNOVER_KEYS = ['turnover_days', 'turnoverDays', 'stock_turnover_days', 'turnover']

/** KPI 概览：平均损耗率 / 平均要货准确率 / 超标门店数 */
const kpiStats = computed(() => {
  const rows = kpiRows.value
  const avg = (pick: (r: KpiRow) => number): string =>
    rows.length ? formatPercent(rows.reduce((sum, r) => sum + pick(r), 0) / rows.length) : '—'
  return [
    { label: '门店数', value: String(rows.length) },
    { label: '平均损耗率', value: avg((r) => r.loss_rate) },
    { label: '平均要货准确率', value: avg((r) => r.order_accuracy) },
    {
      label: '损耗率超标门店',
      value: String(rows.filter((r) => r.loss_rate > LOSS_RATE_WARN).length)
    }
  ]
})

/**
 * 逐店查询盈亏与 KPI。
 * §8.2 无批量端点：选择「全部门店」时对每家门店分别调用 profit + kpi 两个端点，
 * 用 allSettled 保证个别门店失败不影响其余行。
 */
async function fetchKpi(): Promise<void> {
  if (!kpiPeriod.value) {
    ElMessage.warning('请先选择对账周期')
    return
  }
  const ids = kpiStoreId.value === undefined ? stores.value.map((s) => s.id) : [kpiStoreId.value]
  if (!ids.length) {
    ElMessage.warning('暂无门店可选，请确认门店主数据已维护')
    return
  }
  kpiLoading.value = true
  kpiQueried.value = true
  profitDetail.value = null
  try {
    const results = await Promise.allSettled(
      ids.map(async (id) => {
        const [profit, kpi] = await Promise.all([
          getStoreProfit(id, kpiPeriod.value),
          getStoreKpi(id, kpiPeriod.value)
        ])
        return { id, profit, kpi }
      })
    )

    const rows: KpiRow[] = []
    let fails = 0
    results.forEach((result) => {
      if (result.status === 'rejected') {
        fails += 1
        return
      }
      const { id, profit, kpi } = result.value
      const revenue = readNum(profit, REVENUE_KEYS) || readNum(kpi, REVENUE_KEYS)
      const gross = readNum(profit, GROSS_KEYS) || readNum(kpi, GROSS_KEYS)
      const margin = readNum(profit, MARGIN_KEYS) || (revenue > 0 ? (gross / revenue) * 100 : 0)
      const store = storeMap.value.get(id)
      rows.push({
        store_id: id,
        store_name: profit.store_name || kpi.store_name || (store ? store.name : '门店#' + id),
        revenue,
        gross_profit: gross,
        gross_margin: margin,
        loss_rate: readNum(kpi, LOSS_RATE_KEYS),
        order_accuracy: readNum(kpi, ACCURACY_KEYS),
        turnover_days: readNum(kpi, TURNOVER_KEYS)
      })
      if (ids.length === 1) profitDetail.value = profit
    })

    kpiRows.value = rows
    kpiFails.value = fails
    if (fails > 0) ElMessage.warning(fails + ' 家门店的盈亏/KPI 数据加载失败，已跳过')
  } catch {
    kpiRows.value = []
  } finally {
    kpiLoading.value = false
  }
}

/** 损耗率超标整行标红（Element 行样式需 :deep 覆盖 td 背景） */
function kpiRowClass({ row }: { row: KpiRow }): string {
  return row.loss_rate > LOSS_RATE_WARN ? 'danger-row' : ''
}

onMounted(async () => {
  try {
    const res = await getStores({ page: 1, page_size: 200 })
    stores.value = res?.list ?? []
  } catch {
    // 门店主数据加载失败不阻塞对账单查询
  }
  await fetchBills()
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2><span class="brand-name">念家鲜饺</span>对账与 KPI</h2>
      <router-link to="/">← 返回首页</router-link>
    </div>

    <!-- 概览卡片：随 Tab 切换 -->
    <div class="stat-row">
      <div v-for="s in (activeTab === 'bill' ? billStats : kpiStats)" :key="s.label" class="stat-card">
        <div class="stat-label">{{ s.label }}</div>
        <div class="stat-value">{{ s.value }}</div>
      </div>
    </div>

    <el-card shadow="never">
      <el-tabs v-model="activeTab">
        <!-- ===== 对账单 ===== -->
        <el-tab-pane label="对账单" name="bill">
          <div class="toolbar">
            <span class="label">对账周期</span>
            <el-date-picker
              v-model="billPeriodDate"
              type="week"
              value-format="YYYY-MM-DD"
              placeholder="选择对账周"
              style="width: 200px"
            />
            <el-select
              v-model="billFilterStoreId"
              placeholder="全部门店"
              clearable
              filterable
              style="width: 220px"
            >
              <el-option
                v-for="s in stores"
                :key="s.id"
                :label="s.name + '（' + s.store_no + '）'"
                :value="s.id"
              />
            </el-select>
            <el-button type="primary" @click="handleSearchBills">查询</el-button>
            <el-button @click="handleResetBills">重置</el-button>
            <el-button v-if="canGenerate" type="primary" plain @click="openGenerate">
              生成对账单
            </el-button>
            <span v-if="!canGenerate" class="hint">生成对账需管理员权限（reconcile:generate）</span>
          </div>

          <div class="period-line">
            <span class="muted">当前周期：{{ billPeriod || '—' }}（ISO 周，形如 2026-W42）</span>
            <span class="muted">实收金额 = 内部结算额 − 与管家婆差异额（§7.5 两列金额口径）</span>
          </div>

          <el-table
            v-loading="billLoading"
            :data="bills"
            border
            stripe
            empty-text="该周期暂无对账单（可先「生成对账单」）"
          >
            <el-table-column label="门店" min-width="170">
              <template #default="{ row }">{{ row.store_name || storeName(row.store_id) }}</template>
            </el-table-column>
            <el-table-column prop="period" label="周期" width="110" />
            <el-table-column label="应配金额" width="150" align="right">
              <template #default="{ row }">{{ formatMoney(payableOf(asReconcile(row))) }}</template>
            </el-table-column>
            <el-table-column label="实收金额" width="150" align="right">
              <template #default="{ row }">{{ formatMoney(receivedOf(asReconcile(row))) }}</template>
            </el-table-column>
            <el-table-column label="差异金额" width="150" align="right">
              <template #default="{ row }">
                <span :class="Number(row.diff_amount) === 0 ? '' : (Number(row.diff_amount) < 0 ? 'diff-down' : 'diff-up')">
                  {{ formatDiff(row.diff_amount) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="reconcileStatusTag(row.status)" effect="light">
                  {{ reconcileStatusText(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="确认时间" width="150">
              <template #default="{ row }">{{ formatDateTime(row.confirmed_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="110" fixed="right">
              <template #default="{ row }">
                <el-button
                  v-if="canConfirm && row.status === 'draft'"
                  link
                  type="primary"
                  @click="openConfirm(asReconcile(row))"
                >
                  确认
                </el-button>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
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

        <!-- ===== 门店 KPI ===== -->
        <el-tab-pane label="门店 KPI" name="kpi">
          <div class="toolbar">
            <el-select
              v-model="kpiStoreId"
              placeholder="全部门店"
              clearable
              filterable
              style="width: 220px"
            >
              <el-option
                v-for="s in stores"
                :key="s.id"
                :label="s.name + '（' + s.store_no + '）'"
                :value="s.id"
              />
            </el-select>
            <el-date-picker
              v-model="kpiPeriodDate"
              type="week"
              value-format="YYYY-MM-DD"
              placeholder="选择对账周"
              style="width: 200px"
            />
            <el-button type="primary" :loading="kpiLoading" @click="fetchKpi">查询 KPI</el-button>
            <span class="hint">
              周期 {{ kpiPeriod || '—' }}；全部门店 = 逐店调用 /stores/{id}/profit 与 /stores/{id}/kpi
            </span>
          </div>

          <el-alert
            class="loss-alert"
            type="warning"
            :closable="false"
            show-icon
            title="损耗率超过 3% 的门店整行标红，需重点复盘订货与储存环节。"
          />

          <el-table
            v-loading="kpiLoading"
            :data="kpiRows"
            border
            stripe
            :row-class-name="kpiRowClass"
            empty-text="请选择门店与周期后点击「查询 KPI」"
          >
            <el-table-column label="门店" min-width="180">
              <template #default="{ row }">{{ row.store_name || storeName(row.store_id) }}</template>
            </el-table-column>
            <el-table-column label="营业额(元)" width="150" align="right">
              <template #default="{ row }">{{ formatMoney(row.revenue) }}</template>
            </el-table-column>
            <el-table-column label="毛利(元)" width="140" align="right">
              <template #default="{ row }">{{ formatMoney(row.gross_profit) }}</template>
            </el-table-column>
            <el-table-column label="毛利率" width="110" align="right">
              <template #default="{ row }">{{ formatPercent(row.gross_margin) }}</template>
            </el-table-column>
            <el-table-column label="损耗率" width="110" align="right">
              <template #default="{ row }">
                <span :class="row.loss_rate > LOSS_RATE_WARN ? 'loss-warn' : ''">
                  {{ formatPercent(row.loss_rate) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="要货准确率" width="130" align="right">
              <template #default="{ row }">{{ formatPercent(row.order_accuracy) }}</template>
            </el-table-column>
            <el-table-column label="周转天数" width="120" align="right">
              <template #default="{ row }">{{ formatDays(row.turnover_days) }}</template>
            </el-table-column>
          </el-table>

          <p v-if="kpiQueried && !kpiRows.length && !kpiLoading" class="muted empty-note">
            未获取到 KPI 数据<span v-if="kpiFails">（{{ kpiFails }} 家门店加载失败）</span>。
          </p>

          <!-- 单店盈亏明细（GET /stores/{id}/profit?period=） -->
          <div v-if="profitDetail" class="profit-block">
            <div class="sub-head">
              <span class="sub-title">盈亏明细</span>
              <span class="muted">
                {{ profitDetail.store_name || storeName(profitDetail.store_id) }} ·
                {{ profitDetail.period || kpiPeriod }}
              </span>
            </div>
            <div class="stat-row profit-row">
              <div class="stat-card">
                <div class="stat-label">营业额</div>
                <div class="stat-value">{{ formatMoney(readNum(profitDetail, REVENUE_KEYS)) }}</div>
              </div>
              <div class="stat-card">
                <div class="stat-label">配货成本</div>
                <div class="stat-value">
                  {{ formatMoney(readNum(profitDetail, ['dispatch_amount', 'dispatchAmount', 'cost_amount', 'total_amount'])) }}
                </div>
              </div>
              <div class="stat-card">
                <div class="stat-label">报损金额</div>
                <div class="stat-value">
                  {{ formatMoney(readNum(profitDetail, ['loss_amount', 'lossAmount', 'loss'])) }}
                </div>
              </div>
              <div class="stat-card">
                <div class="stat-label">毛利</div>
                <div class="stat-value">{{ formatMoney(readNum(profitDetail, GROSS_KEYS)) }}</div>
              </div>
              <div class="stat-card">
                <div class="stat-label">毛利率</div>
                <div class="stat-value">{{ formatPercent(readNum(profitDetail, MARGIN_KEYS)) }}</div>
              </div>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 生成对账单：POST /reconciles/generate -->
    <el-dialog v-model="genVisible" title="生成对账单" width="520px" destroy-on-close>
      <el-form label-width="100px">
        <el-form-item label="对账周期">
          <el-input :model-value="billPeriod" disabled />
          <span class="hint">周期取工具栏所选周（ISO 周，如 2026-W42）</span>
        </el-form-item>
        <el-form-item label="生成范围">
          <el-select v-model="genStoreId" placeholder="全部门店" clearable filterable style="width: 100%">
            <el-option
              v-for="s in stores"
              :key="s.id"
              :label="s.name + '（' + s.store_no + '）'"
              :value="s.id"
            />
          </el-select>
          <span class="hint">留空表示按该周期生成全部门店对账单</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="genVisible = false">取消</el-button>
        <el-button type="primary" :loading="generating" @click="submitGenerate">生成</el-button>
      </template>
    </el-dialog>

    <!-- 确认对账：POST /reconciles/{id}/confirm -->
    <el-dialog v-model="confirmVisible" title="确认对账单" width="520px" destroy-on-close>
      <el-descriptions v-if="confirmTarget" :column="1" border size="small">
        <el-descriptions-item label="门店">
          {{ confirmTarget.store_name || storeName(confirmTarget.store_id) }}
        </el-descriptions-item>
        <el-descriptions-item label="周期">{{ confirmTarget.period }}</el-descriptions-item>
        <el-descriptions-item label="应配金额">
          {{ formatMoney(payableOf(confirmTarget)) }}
        </el-descriptions-item>
        <el-descriptions-item label="实收金额">
          {{ formatMoney(receivedOf(confirmTarget)) }}
        </el-descriptions-item>
      </el-descriptions>
      <el-form label-width="100px" style="margin-top: 12px">
        <el-form-item label="差异额(元)">
          <el-input-number v-model="confirmDiff" :precision="2" :step="10" style="width: 200px" />
          <span class="hint">与管家婆台账的差异，正=台账多出，负=实际少收</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="confirmVisible = false">取消</el-button>
        <el-button type="primary" :loading="confirming" @click="submitConfirm">确认对账</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  padding: 24px;
}
/* 顶栏：毛玻璃白底（Apple 式克制） */
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
  border: 1px solid rgba(26, 26, 26, 0.06);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.8);
  -webkit-backdrop-filter: blur(16px);
  backdrop-filter: blur(16px);
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
/* 概览卡片：白卡 + 16px 圆角 + 柔和阴影（大数字，Apple 式留白） */
.stat-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 20px;
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
.profit-block {
  margin-top: 20px;
}
.profit-row {
  grid-template-columns: repeat(5, minmax(0, 1fr));
  margin-bottom: 0;
}
.sub-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 10px;
}
.sub-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--nf-ink);
}
.page :deep(.el-card) {
  border: none;
  border-radius: 16px;
  box-shadow: var(--nf-shadow-card);
  background: #ffffff;
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.label {
  font-size: 14px;
  color: #3c3c3c;
}
.period-line {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 10px;
}
.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
.hint,
.muted {
  color: var(--nf-muted);
  font-size: 12px;
}
.empty-note {
  margin: 10px 0 0;
}
.loss-alert {
  margin-bottom: 12px;
}
/* 差异金额：正=台账多出（品牌绿），负=实际少收（品牌橙红告警） */
.diff-up {
  color: var(--nf-green);
  font-weight: 600;
}
.diff-down {
  color: #e2604a;
  font-weight: 600;
}
.loss-warn {
  color: #e2604a;
  font-weight: 700;
}
/* 损耗率超标整行标红：Element 行背景需覆盖 td.el-table__cell 才可见 */
.page :deep(.el-table .danger-row td.el-table__cell) {
  background: rgba(226, 96, 74, 0.08);
  color: #e2604a;
}
@media (max-width: 1200px) {
  .profit-row {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
@media (max-width: 900px) {
  .stat-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
