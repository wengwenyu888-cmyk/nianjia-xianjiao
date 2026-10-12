<script setup lang="ts">
// 司机任务（司机视角）：当日配送任务卡片 + 发车 + 签收（填实收数量，支持差异）
// 接口（§8.2 配送签收，路径与方法逐字对齐）：
//   GET /deliveries?driver_id=&require_date= · GET /deliveries/{id}
//   POST /deliveries/{id}/depart · POST /deliveries/{id}/sign · GET /signs/{id}
import { computed, onMounted, reactive, ref } from 'vue'
import dayjs from 'dayjs'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  departDelivery,
  getDelivery,
  getSign,
  listDeliveries,
  newIdempotencyKey,
  signDelivery,
  type Delivery,
  type DeliveryItem,
  type DeliveryStatus,
  type Sign
} from '@/api/delivery'
import { getSkus, getStores, type Sku, type Store } from '@/api/store'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()

// ---- 身份：司机账号按 user.id 查本人任务；非司机账号可手填 driver_id 代查 ----
const isDriver = computed(() => userStore.roleCodes.includes('driver'))
const driverId = ref<number | undefined>(userStore.user?.id ?? undefined)

/** 配送日期：默认当日（§8.2 require_date 为 DATE，格式 YYYY-MM-DD） */
const requireDate = ref(dayjs().format('YYYY-MM-DD'))
/** 中文星期：dayjs 默认 dddd 输出英文，这里手写映射（不引入 locale 依赖） */
const WEEKDAYS = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六']

/** 配送日期的中文展示，用于页头 */
const todayText = computed(() => {
  const d = dayjs(requireDate.value)
  return d.isValid() ? d.format('YYYY-MM-DD') + ' ' + WEEKDAYS[d.day()] : requireDate.value
})

// ---- 状态字典（§7.4 delivery.status） ----
const statusOptions: {
  value: DeliveryStatus
  label: string
  tag: 'info' | 'warning' | 'success' | 'danger'
}[] = [
  { value: 'loaded', label: '已装车', tag: 'info' },
  { value: 'on_way', label: '配送中', tag: 'warning' },
  { value: 'signed', label: '已签收', tag: 'success' },
  { value: 'partial', label: '部分签收', tag: 'warning' },
  { value: 'rejected', label: '拒收', tag: 'danger' }
]

function statusText(s: DeliveryStatus): string {
  return statusOptions.find((it) => it.value === s)?.label ?? s
}

function statusTag(s: DeliveryStatus): 'info' | 'warning' | 'success' | 'danger' {
  return statusOptions.find((it) => it.value === s)?.tag ?? 'info'
}

/** 签收单状态文案（§7.4 sign.status） */
function signStatusText(s: string): string {
  return s === 'full' ? '全部签收' : s === 'partial' ? '部分签收' : s === 'reject' ? '拒收' : s
}

// ---- 格式化 ----
/** 数量：最多 3 位小数（§7 DECIMAL(14,3)）；字符串数值一并归一 */
function formatQty(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 3 })
}

/** 时间戳：ISO8601 → YYYY-MM-DD HH:mm */
function formatDateTime(v: string | null | undefined): string {
  if (!v) return '—'
  const d = dayjs(v)
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm') : v
}

// ---- 主数据映射：任务只给 store_id/sku_id，名称与地址由主数据接口补齐 ----
const stores = ref<Store[]>([])
const skus = ref<Sku[]>([])
const storeMap = computed(() => new Map(stores.value.map((s) => [s.id, s])))
const skuMap = computed(() => new Map(skus.value.map((s) => [s.id, s])))

function storeName(id: number): string {
  const s = storeMap.value.get(id)
  return s ? s.name : '门店#' + id
}

/** 门店地址（§7.1 store.address）：司机导航用，缺失显示 — */
function storeAddress(id: number): string {
  return storeMap.value.get(id)?.address || '—'
}

function skuName(id: number, fallback?: string | null): string {
  const s = skuMap.value.get(id)
  return fallback || (s ? s.name : 'SKU#' + id)
}

// ---- 任务列表 ----
const loading = ref(false)
const tasks = ref<Delivery[]>([])

/** 明细缓存：列表接口不保证带明细，点开卡片时才按需拉 GET /deliveries/{id} */
const detailMap = reactive<Record<number, Delivery>>({})
const loadingDetailId = ref<number | null>(null)
/** 签收结果缓存：签收接口返回的签收单（含 id），便于随后查看详情 */
const signInfoMap = reactive<Record<number, Sign>>({})

function itemsOf(row: Delivery): DeliveryItem[] {
  return detailMap[row.id]?.items ?? row.items ?? []
}

/** 件数摘要：明细已加载算合计，否则用后端汇总字段降级 */
function qtySummary(row: Delivery): string {
  const items = itemsOf(row)
  if (items.length) {
    const total = items.reduce((sum, it) => sum + Number(it.qty_base || 0), 0)
    return items.length + ' 项 · 合计 ' + formatQty(total)
  }
  if (row.item_count !== null && row.item_count !== undefined) return row.item_count + ' 项'
  if (row.qty_total !== null && row.qty_total !== undefined) return formatQty(row.qty_total)
  return '待展开'
}

const doneCount = computed(
  () => tasks.value.filter((t) => t.status === 'signed' || t.status === 'partial').length
)

async function fetchTasks(): Promise<void> {
  loading.value = true
  try {
    const res = await listDeliveries({
      driver_id: driverId.value,
      require_date: requireDate.value || undefined,
      page: 1,
      page_size: 100
    })
    tasks.value = res?.list ?? []
  } catch {
    // request.ts 已统一提示错误
    tasks.value = []
  } finally {
    loading.value = false
  }
}

async function loadMasterData(): Promise<void> {
  const [storeRes, skuRes] = await Promise.allSettled([
    getStores({ page: 1, page_size: 200 }),
    getSkus({ page: 1, page_size: 200 })
  ])
  if (storeRes.status === 'fulfilled') stores.value = storeRes.value?.list ?? []
  if (skuRes.status === 'fulfilled') skus.value = skuRes.value?.list ?? []
}

/** 展开/收起明细：首次展开时按需拉详情 */
async function toggleDetail(row: Delivery): Promise<void> {
  if (detailMap[row.id]) {
    delete detailMap[row.id]
    return
  }
  loadingDetailId.value = row.id
  try {
    detailMap[row.id] = await getDelivery(row.id)
  } catch {
    // 详情拉取失败：保持收起，request.ts 已提示
  } finally {
    loadingDetailId.value = null
  }
}

// ---- 发车（POST /deliveries/{id}/depart） ----
const departingId = ref<number | null>(null)

async function handleDepart(row: Delivery): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '确认发车前往 ' + storeName(row.store_id) + '？',
      '发车确认',
      { type: 'warning', confirmButtonText: '确认发车', cancelButtonText: '取消' }
    )
  } catch {
    return // 用户取消
  }
  departingId.value = row.id
  try {
    await departDelivery(row.id)
    ElMessage.success('已发车：' + storeName(row.store_id))
    await fetchTasks()
  } catch {
    // request.ts 已统一提示（状态流转冲突返回 40900）
  } finally {
    departingId.value = null
  }
}

// ---- 签收（POST /deliveries/{id}/sign，带明细实收数量） ----
interface SignRow {
  sku_id: number
  batch_no: string
  send_qty_base: number
  sign_qty_base: number
}

/** el-table 插槽 row 为 DefaultRow，传给 SignRow 处理函数前显式收窄 */
function asSignRow(row: unknown): SignRow {
  return row as SignRow
}

const signVisible = ref(false)
const signing = ref(false)
const signTarget = ref<Delivery | null>(null)
const signRows = ref<SignRow[]>([])
const signRemark = ref('')
/** 本次签收的幂等键：重复提交（网络重试）复用同一个键，§7.4 sign.uk_idem */
const signKey = ref(newIdempotencyKey())

/** 差异行数：实收与应送不一致的明细条数，用于提交前提示 */
const diffRowCount = computed(
  () => signRows.value.filter((r) => Number(r.sign_qty_base) !== Number(r.send_qty_base)).length
)

async function openSign(row: Delivery): Promise<void> {
  let items = itemsOf(row)
  if (!items.length) {
    try {
      items = (await getDelivery(row.id)).items ?? []
    } catch {
      return // 明细拉取失败，request.ts 已提示
    }
  }
  if (!items.length) {
    ElMessage.warning('该配送单暂无装车明细，无法签收')
    return
  }
  signTarget.value = row
  signRows.value = items.map((it) => ({
    sku_id: it.sku_id,
    batch_no: it.batch_no,
    send_qty_base: Number(it.qty_base || 0),
    sign_qty_base: Number(it.qty_base || 0) // 默认全部收齐，差异由店长/司机手工改
  }))
  signRemark.value = ''
  signKey.value = newIdempotencyKey()
  signVisible.value = true
}

/** 差异 = 应送 - 实收（§7.4 sign_item.diff_qty_base 生成列，正数少送、负数多收） */
function diffOf(row: SignRow): number {
  return Number(row.send_qty_base || 0) - Number(row.sign_qty_base || 0)
}

function diffClass(row: SignRow): string {
  const diff = diffOf(row)
  if (diff > 0) return 'diff-short'
  if (diff < 0) return 'diff-over'
  return ''
}

async function submitSign(): Promise<void> {
  const target = signTarget.value
  if (!target) return
  for (let i = 0; i < signRows.value.length; i += 1) {
    const qty = Number(signRows.value[i].sign_qty_base)
    if (Number.isNaN(qty) || qty < 0) {
      ElMessage.warning('第 ' + (i + 1) + ' 行：实收数量需 ≥ 0')
      return
    }
  }
  signing.value = true
  try {
    const sign = await signDelivery(
      target.id,
      {
        items: signRows.value.map((r) => ({
          sku_id: r.sku_id,
          batch_no: r.batch_no,
          sign_qty_base: Number(r.sign_qty_base)
        })),
        remark: signRemark.value.trim() || null
      },
      signKey.value
    )
    if (sign?.id) signInfoMap[target.id] = sign
    ElMessage.success(
      diffRowCount.value > 0 ? '签收完成（含 ' + diffRowCount.value + ' 项差异）' : '签收完成'
    )
    signVisible.value = false
    await fetchTasks()
  } catch {
    // request.ts 已统一提示（重复签收返回 40900）
  } finally {
    signing.value = false
  }
}

// ---- 签收单查看（GET /signs/{id}） ----
const signViewVisible = ref(false)
const signViewLoading = ref(false)
const signView = ref<Sign | null>(null)

async function openSignView(row: Delivery): Promise<void> {
  const signId = row.sign_id ?? signInfoMap[row.id]?.id
  if (!signId) {
    ElMessage.info('列表未返回签收单 ID，暂无法查看签收单详情')
    return
  }
  signViewVisible.value = true
  signViewLoading.value = true
  signView.value = null
  try {
    signView.value = await getSign(signId)
  } catch {
    signViewVisible.value = false
  } finally {
    signViewLoading.value = false
  }
}

onMounted(async () => {
  await loadMasterData()
  await fetchTasks()
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2><span class="brand-name">念家鲜饺</span>司机任务</h2>
      <router-link to="/">← 返回首页</router-link>
    </div>

    <!-- 司机信息条：司机 + 日期 + 今日进度 -->
    <div class="driver-bar">
      <div class="driver-main">
        <div class="driver-name">
          {{ isDriver ? '司机 ' + userStore.displayName : '配送任务代查' }}
        </div>
        <div class="driver-sub">{{ todayText }} · 共 {{ tasks.length }} 单</div>
      </div>
      <div class="driver-side">
        <el-tag effect="dark" size="small">今日 {{ tasks.length }} 单</el-tag>
        <el-tag type="success" effect="dark" size="small">已完成 {{ doneCount }} 单</el-tag>
      </div>
    </div>

    <div class="toolbar">
      <el-date-picker
        v-model="requireDate"
        type="date"
        value-format="YYYY-MM-DD"
        placeholder="配送日期"
        style="width: 180px"
        @change="fetchTasks"
      />
      <el-input-number
        v-if="!isDriver"
        v-model="driverId"
        :min="1"
        :precision="0"
        :controls="false"
        placeholder="司机 user_id"
        style="width: 150px"
      />
      <el-button type="primary" @click="fetchTasks">刷新任务</el-button>
      <span class="muted">
        {{ isDriver ? '按本人 user_id 查当日任务（§8.2 GET /deliveries?driver_id=&require_date=）' : '非司机账号：填写司机 user_id 代查其任务' }}
      </span>
    </div>

    <div v-loading="loading" class="task-wrap">
      <div v-if="tasks.length" class="task-grid">
        <div v-for="row in tasks" :key="row.id" class="task-card">
          <div class="task-top">
            <span class="task-store">{{ row.store_name || storeName(row.store_id) }}</span>
            <el-tag :type="statusTag(row.status)" effect="light" size="small">
              {{ statusText(row.status) }}
            </el-tag>
          </div>
          <div class="task-addr">{{ storeAddress(row.store_id) }}</div>
          <div class="task-meta">
            <span>单号 {{ row.delivery_no }}</span>
            <span>冷链件数：{{ qtySummary(row) }}</span>
            <span>车牌：{{ row.plate_no || '—' }}</span>
          </div>

          <!-- 明细：展开后显示 SKU / 批次 / 发送数量 -->
          <div v-if="detailMap[row.id]" class="task-items">
            <div v-for="(it, idx) in itemsOf(row)" :key="idx" class="task-item-line">
              <span class="task-item-name">{{ skuName(it.sku_id, it.sku_name) }}</span>
              <span class="task-item-qty">{{ it.batch_no }} · {{ formatQty(it.qty_base) }}</span>
            </div>
          </div>

          <div class="task-actions">
            <el-button
              size="small"
              :loading="loadingDetailId === row.id"
              @click="toggleDetail(row)"
            >
              {{ detailMap[row.id] ? '收起明细' : '明细' }}
            </el-button>
            <el-button
              v-if="row.status === 'loaded'"
              type="primary"
              size="small"
              :loading="departingId === row.id"
              @click="handleDepart(row)"
            >
              发车
            </el-button>
            <el-button
              v-else-if="row.status === 'on_way'"
              type="success"
              size="small"
              @click="openSign(row)"
            >
              签收
            </el-button>
            <el-button v-else size="small" @click="openSignView(row)">查看签收单</el-button>
          </div>
        </div>
      </div>

      <el-empty
        v-else-if="!loading"
        description="当日暂无配送任务（可切换日期或确认司机 user_id）"
      />
    </div>

    <!-- 签收：填写实收数量，支持差异 -->
    <el-dialog v-model="signVisible" title="配送签收" width="760px" destroy-on-close>
      <div v-if="signTarget" class="sign-head">
        <span class="sign-store">{{ signTarget.store_name || storeName(signTarget.store_id) }}</span>
        <span class="muted">
          单号 {{ signTarget.delivery_no }} · 要求日期 {{ signTarget.require_date }}
        </span>
      </div>

      <el-table :data="signRows" border stripe size="small" empty-text="暂无装车明细">
        <el-table-column label="SKU" min-width="170">
          <template #default="{ row }">{{ skuName(row.sku_id) }}</template>
        </el-table-column>
        <el-table-column prop="batch_no" label="批次号" width="140" />
        <el-table-column label="应送数量" width="110" align="right">
          <template #default="{ row }">{{ formatQty(row.send_qty_base) }}</template>
        </el-table-column>
        <el-table-column label="实收数量" width="170">
          <template #default="{ row }">
            <el-input-number
              v-model="row.sign_qty_base"
              :min="0"
              :max="row.send_qty_base * 2"
              :precision="3"
              :step="1"
              size="small"
              style="width: 100%"
            />
          </template>
        </el-table-column>
        <el-table-column label="差异" width="110" align="right">
          <template #default="{ row }">
            <span :class="diffClass(asSignRow(row))">{{ formatQty(diffOf(asSignRow(row))) }}</span>
          </template>
        </el-table-column>
      </el-table>

      <div class="sign-note">
        <span class="muted">
          差异 = 应送 - 实收（正数少送、负数多收）；本次有 {{ diffRowCount }} 项存在差异
        </span>
      </div>

      <el-input
        v-model="signRemark"
        type="textarea"
        :rows="2"
        maxlength="255"
        show-word-limit
        placeholder="签收备注（可选，如少送原因、包装破损情况）"
        style="margin-top: 10px"
      />

      <template #footer>
        <el-button @click="signVisible = false">取消</el-button>
        <el-button type="primary" :loading="signing" @click="submitSign">提交签收</el-button>
      </template>
    </el-dialog>

    <!-- 签收单详情：GET /signs/{id} -->
    <el-dialog v-model="signViewVisible" title="签收单详情" width="720px">
      <div v-loading="signViewLoading">
        <el-descriptions v-if="signView" :column="2" border size="small">
          <el-descriptions-item label="签收单号">{{ signView.id }}</el-descriptions-item>
          <el-descriptions-item label="签收状态">
            <el-tag :type="signView.status === 'full' ? 'success' : 'warning'" effect="light">
              {{ signStatusText(signView.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="签收时间">
            {{ formatDateTime(signView.sign_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="签收人">{{ signView.sign_by ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="备注" :span="2">{{ signView.remark || '—' }}</el-descriptions-item>
        </el-descriptions>

        <el-table
          :data="signView?.items ?? []"
          border
          stripe
          size="small"
          empty-text="暂无签收明细"
          style="margin-top: 14px"
        >
          <el-table-column label="SKU" min-width="150">
            <template #default="{ row }">{{ skuName(row.sku_id, row.sku_name) }}</template>
          </el-table-column>
          <el-table-column prop="batch_no" label="批次号" width="140" />
          <el-table-column label="应送数量" width="120" align="right">
            <template #default="{ row }">{{ formatQty(row.send_qty_base) }}</template>
          </el-table-column>
          <el-table-column label="实收数量" width="120" align="right">
            <template #default="{ row }">{{ formatQty(row.sign_qty_base) }}</template>
          </el-table-column>
          <el-table-column label="差异" width="110" align="right">
            <template #default="{ row }">{{ formatQty(row.diff_qty_base) }}</template>
          </el-table-column>
        </el-table>
      </div>
      <template #footer>
        <el-button @click="signViewVisible = false">关闭</el-button>
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
/* 司机信息条：白卡 + 16px 圆角 + 柔和阴影 */
.driver-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding: 18px 22px;
  margin-bottom: 16px;
  background: #ffffff;
  border-radius: 16px;
  box-shadow: var(--nf-shadow-card);
}
.driver-name {
  font-size: 20px;
  font-weight: 800;
  color: var(--nf-ink);
}
.driver-sub {
  margin-top: 4px;
  font-size: 13px;
  color: var(--nf-muted);
}
.driver-side {
  display: flex;
  align-items: center;
  gap: 8px;
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}
.muted {
  color: var(--nf-muted);
  font-size: 12px;
}
/* 任务卡片网格：自适应列宽，卡片 16px 圆角 + 柔和阴影 */
.task-wrap {
  min-height: 120px;
}
.task-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}
.task-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 18px 20px;
  background: #ffffff;
  border: 1px solid transparent;
  border-radius: 16px;
  box-shadow: var(--nf-shadow-card);
  transition: transform 0.2s ease, border-color 0.2s, box-shadow 0.2s;
}
.task-card:hover {
  transform: translateY(-2px);
  border-color: var(--nf-green);
  box-shadow: var(--nf-shadow-card-hover);
}
.task-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
/* 门店名：卡片主标题，20px / 700 */
.task-store {
  font-size: 18px;
  font-weight: 700;
  color: var(--nf-ink);
}
.task-addr {
  font-size: 13px;
  color: var(--nf-muted);
}
.task-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-top: 8px;
  margin-top: 4px;
  border-top: 1px dashed rgba(26, 26, 26, 0.08);
  font-size: 13px;
  color: #3c3c3c;
}
.task-items {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
  border-radius: 10px;
  background: rgba(169, 217, 94, 0.12);
  font-size: 12px;
  color: #3c3c3c;
}
.task-item-line {
  display: flex;
  justify-content: space-between;
  gap: 10px;
}
.task-item-name {
  font-weight: 600;
}
.task-item-qty {
  color: var(--nf-muted);
}
.task-actions {
  display: flex;
  gap: 8px;
  margin-top: 6px;
}
.sign-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 10px;
}
.sign-store {
  font-size: 18px;
  font-weight: 700;
  color: var(--nf-ink);
}
.sign-note {
  margin-top: 8px;
}
/* 差异配色：少送用品牌橙红告警（docs/07 §2），多收用品牌绿 */
.diff-short {
  color: #e2604a;
  font-weight: 600;
}
.diff-over {
  color: var(--nf-green);
  font-weight: 600;
}
</style>
