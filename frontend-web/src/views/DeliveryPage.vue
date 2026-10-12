<script setup lang="ts">
// 配送调度（总部/运营）：按日期查配送单 + 生成配送单（装车）+ 发车 + 明细查看
// 接口（§8.2 配送签收，路径与方法逐字对齐）：
//   POST /deliveries · GET /deliveries?driver_id=&require_date= · GET /deliveries/{id}
//   POST /deliveries/{id}/depart · GET /signs/{id}
import { computed, onMounted, reactive, ref } from 'vue'
import dayjs from 'dayjs'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'

import {
  createDelivery,
  departDelivery,
  getDelivery,
  getSign,
  listDeliveries,
  newIdempotencyKey,
  type Delivery,
  type DeliveryCreatePayload,
  type DeliveryItem,
  type DeliveryStatus,
  type Sign
} from '@/api/delivery'
import { getSkus, getStores, type Sku, type Store } from '@/api/store'

/**
 * el-table 默认插槽的 row 是 Element Plus 的 DefaultRow（只有索引签名），
 * 直接传给具体类型的处理函数会触发 TS2345；这里显式收窄回业务类型。
 */
function asDelivery(row: unknown): Delivery {
  return row as Delivery
}

// ---- 状态字典（§7.4 delivery.status 五态） ----
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

/** 状态转文案；未知状态原样展示，避免后端新增状态时页面空白 */
function statusText(s: DeliveryStatus): string {
  return statusOptions.find((it) => it.value === s)?.label ?? s
}

/** 状态转标签配色 */
function statusTag(s: DeliveryStatus): 'info' | 'warning' | 'success' | 'danger' {
  return statusOptions.find((it) => it.value === s)?.tag ?? 'info'
}

// ---- 格式化：后端 DECIMAL 可能以字符串下发，统一 Number 归一 ----
/** 数量：最多 3 位小数（§7 DECIMAL(14,3)），整数不补小数位 */
function formatQty(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 3 })
}

/** 时间戳：ISO8601 → YYYY-MM-DD HH:mm（§8.1 时间约定） */
function formatDateTime(v: string | null | undefined): string {
  if (!v) return '—'
  const d = dayjs(v)
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm') : v
}

// ---- 主数据映射：配送单只给 store_id/sku_id，名称由主数据接口补齐 ----
const stores = ref<Store[]>([])
const skus = ref<Sku[]>([])
const storeMap = computed(() => new Map(stores.value.map((s) => [s.id, s])))
const skuMap = computed(() => new Map(skus.value.map((s) => [s.id, s])))

function storeName(id: number): string {
  const s = storeMap.value.get(id)
  return s ? s.name : '门店#' + id
}

function skuName(id: number, fallback?: string | null): string {
  const s = skuMap.value.get(id)
  return fallback || (s ? s.name : 'SKU#' + id)
}

// ---- 列表状态 ----
const loading = ref(false)
const list = ref<Delivery[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

const query = reactive<{
  require_date: string
  driver_id: number | undefined
  status: DeliveryStatus | ''
}>({
  require_date: dayjs().format('YYYY-MM-DD'),
  driver_id: undefined,
  status: ''
})

/**
 * 状态筛选：§8.2 只定义 GET /deliveries?driver_id=&require_date= 两个查询参数，
 * 故状态筛选在当前页数据上本地过滤，不擅自扩展接口参数。
 */
const filteredList = computed<Delivery[]>(() =>
  query.status ? list.value.filter((r) => r.status === query.status) : list.value
)

/** 当日概览（当前页聚合；§8.2 未提供配送单汇总端点，故不做后端统计） */
const stats = computed(() => {
  const rows = filteredList.value
  const by = (s: DeliveryStatus): number => rows.filter((r) => r.status === s).length
  return [
    { label: '配送单', value: String(rows.length) },
    { label: '已装车', value: String(by('loaded')) },
    { label: '配送中', value: String(by('on_way')) },
    { label: '已完成', value: String(by('signed') + by('partial')) }
  ]
})

/** 装车明细摘要：明细已加载显示条数，否则用后端汇总字段降级 */
function itemSummary(row: Delivery): string {
  if (row.items?.length) return row.items.length + ' 项'
  if (row.item_count !== null && row.item_count !== undefined) return row.item_count + ' 项'
  return '—'
}

async function fetchList(): Promise<void> {
  loading.value = true
  try {
    const res = await listDeliveries({
      page: page.value,
      page_size: pageSize.value,
      require_date: query.require_date || undefined,
      driver_id: query.driver_id
    })
    list.value = res?.list ?? []
    total.value = res?.total ?? 0
  } catch {
    // request.ts 已统一提示错误，这里置空保证页面可用
    list.value = []
    total.value = 0
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

function handleSearch(): void {
  page.value = 1
  void fetchList()
}

function handleReset(): void {
  query.require_date = dayjs().format('YYYY-MM-DD')
  query.driver_id = undefined
  query.status = ''
  handleSearch()
}

function handleCurrentChange(p: number): void {
  page.value = p
  void fetchList()
}

function handleSizeChange(size: number): void {
  pageSize.value = size
  page.value = 1
  void fetchList()
}

// ---- 发车（POST /deliveries/{id}/depart） ----
const departingId = ref<number | null>(null)

async function handleDepart(row: Delivery): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '确认配送单 ' + row.delivery_no + ' 发车？发车后状态流转为「配送中」。',
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
    await fetchList()
  } catch {
    // request.ts 已统一提示（状态冲突返回 40900）
  } finally {
    departingId.value = null
  }
}

// ---- 明细查看（GET /deliveries/{id}） ----
const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<Delivery | null>(null)

async function openDetail(row: Delivery): Promise<void> {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = row // 先用列表行兜底展示单据头，避免白屏
  try {
    detail.value = await getDelivery(row.id)
  } catch {
    // 保留列表行数据，明细区为空态
  } finally {
    detailLoading.value = false
  }
}

function detailItems(): DeliveryItem[] {
  return detail.value?.items ?? []
}

// ---- 签收单查看（GET /signs/{id}） ----
const signVisible = ref(false)
const signLoading = ref(false)
const signDetail = ref<Sign | null>(null)

async function openSign(row: Delivery): Promise<void> {
  if (!row.sign_id) return
  signVisible.value = true
  signLoading.value = true
  signDetail.value = null
  try {
    signDetail.value = await getSign(row.sign_id)
  } catch {
    signVisible.value = false
  } finally {
    signLoading.value = false
  }
}

/** 签收状态文案（§7.4 sign.status） */
function signStatusText(s: string): string {
  return s === 'full' ? '全部签收' : s === 'partial' ? '部分签收' : s === 'reject' ? '拒收' : s
}

// ---- 生成配送单（装车）（POST /deliveries） ----
interface ItemRow {
  sku_id: number | null
  batch_no: string
  qty_base: number
}

const createVisible = ref(false)
const creating = ref(false)
const createFormRef = ref<FormInstance>()
/** 本次提交的幂等键：同一张单失败重试复用，成功后重新生成（§8.1 幂等） */
const createKey = ref(newIdempotencyKey())

const createForm = reactive<{
  summary_id: number | undefined
  store_id: number | undefined
  require_date: string
  driver_id: number | undefined
  plate_no: string
  items: ItemRow[]
}>({
  summary_id: undefined,
  store_id: undefined,
  require_date: dayjs().format('YYYY-MM-DD'),
  driver_id: undefined,
  plate_no: '',
  items: []
})

/** 表头校验：汇总单与门店为必填（§7.4 delivery.summary_id/store_id 均为非空列） */
const createRules: FormRules = {
  summary_id: [{ required: true, message: '请输入来源汇总单 ID', trigger: 'change' }],
  store_id: [{ required: true, message: '请选择配送门店', trigger: 'change' }],
  require_date: [{ required: true, message: '请选择要求配送日期', trigger: 'change' }]
}

function emptyItemRow(): ItemRow {
  return { sku_id: null, batch_no: '', qty_base: 1 }
}

function addItemRow(): void {
  createForm.items.push(emptyItemRow())
}

function removeItemRow(index: number): void {
  createForm.items.splice(index, 1)
}

function openCreate(): void {
  createForm.summary_id = undefined
  createForm.store_id = undefined
  createForm.require_date = dayjs().format('YYYY-MM-DD')
  createForm.driver_id = undefined
  createForm.plate_no = ''
  createForm.items = [emptyItemRow()]
  createKey.value = newIdempotencyKey()
  createVisible.value = true
}

/** 装车明细逐行校验（动态行不用 el-form rules，避免下标耦合） */
function itemRowError(): string | null {
  if (!createForm.items.length) return '请至少添加一条装车明细'
  for (let i = 0; i < createForm.items.length; i += 1) {
    const row = createForm.items[i]
    if (row.sku_id === null) return '第 ' + (i + 1) + ' 行：请选择 SKU'
    if (!row.batch_no.trim()) return '第 ' + (i + 1) + ' 行：请填写批次号'
    if (!(Number(row.qty_base) > 0)) return '第 ' + (i + 1) + ' 行：装车数量需大于 0'
  }
  return null
}

async function submitCreate(): Promise<void> {
  if (!createFormRef.value) return
  const valid = await createFormRef.value.validate().catch(() => false)
  if (!valid) return
  const rowError = itemRowError()
  if (rowError) {
    ElMessage.warning(rowError)
    return
  }
  creating.value = true
  try {
    const payload: DeliveryCreatePayload = {
      summary_id: Number(createForm.summary_id),
      store_id: Number(createForm.store_id),
      require_date: createForm.require_date,
      driver_id: createForm.driver_id ?? null,
      plate_no: createForm.plate_no.trim() || null,
      items: createForm.items.map((it) => ({
        sku_id: Number(it.sku_id),
        batch_no: it.batch_no.trim(),
        qty_base: Number(it.qty_base)
      }))
    }
    await createDelivery(payload, createKey.value)
    ElMessage.success('配送单已生成')
    createVisible.value = false
    await fetchList()
  } catch {
    // request.ts 已统一提示（幂等键重复返回 40900）
  } finally {
    creating.value = false
  }
}

onMounted(async () => {
  await loadMasterData()
  await fetchList()
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2><span class="brand-name">念家鲜饺</span>配送调度</h2>
      <router-link to="/">← 返回首页</router-link>
    </div>

    <!-- 当日概览：大字号数字卡片，Apple 式留白 -->
    <div class="stat-row">
      <div v-for="s in stats" :key="s.label" class="stat-card">
        <div class="stat-label">{{ s.label }}</div>
        <div class="stat-value">{{ s.value }}</div>
      </div>
    </div>

    <el-card shadow="never">
      <div class="toolbar">
        <el-date-picker
          v-model="query.require_date"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="要求配送日期"
          clearable
          style="width: 180px"
        />
        <el-input-number
          v-model="query.driver_id"
          :min="1"
          :precision="0"
          :controls="false"
          placeholder="司机 user_id"
          style="width: 140px"
        />
        <el-select
          v-model="query.status"
          placeholder="全部状态"
          clearable
          style="width: 150px"
        >
          <el-option
            v-for="it in statusOptions"
            :key="it.value"
            :label="it.label"
            :value="it.value"
          />
        </el-select>
        <el-button type="primary" @click="handleSearch">查询</el-button>
        <el-button @click="handleReset">重置</el-button>
        <el-button type="primary" plain @click="openCreate">生成配送单</el-button>
        <span class="hint">状态筛选作用于当前页（§8.2 配送单列表未定义 status 查询参数）</span>
      </div>

      <el-table v-loading="loading" :data="filteredList" border stripe empty-text="暂无配送单">
        <el-table-column prop="delivery_no" label="配送单号" width="180" />
        <el-table-column prop="require_date" label="要求日期" width="120" />
        <el-table-column label="门店" min-width="160">
          <template #default="{ row }">{{ row.store_name || storeName(row.store_id) }}</template>
        </el-table-column>
        <el-table-column label="司机" width="90">
          <template #default="{ row }">{{ row.driver_id ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="车牌" width="110">
          <template #default="{ row }">{{ row.plate_no || '—' }}</template>
        </el-table-column>
        <el-table-column label="装车明细" width="110" align="right">
          <template #default="{ row }">{{ itemSummary(asDelivery(row)) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status)" effect="light">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(asDelivery(row))">明细</el-button>
            <el-button
              v-if="row.status === 'loaded'"
              link
              type="primary"
              :loading="departingId === row.id"
              @click="handleDepart(asDelivery(row))"
            >
              发车
            </el-button>
            <el-button v-if="row.sign_id" link type="primary" @click="openSign(asDelivery(row))">
              签收单
            </el-button>
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
    </el-card>

    <!-- 明细查看：GET /deliveries/{id} -->
    <el-dialog v-model="detailVisible" title="配送单明细" width="760px">
      <div v-loading="detailLoading">
        <el-descriptions v-if="detail" :column="2" border size="small">
          <el-descriptions-item label="配送单号">{{ detail.delivery_no }}</el-descriptions-item>
          <el-descriptions-item label="要求日期">{{ detail.require_date }}</el-descriptions-item>
          <el-descriptions-item label="门店">
            {{ detail.store_name || storeName(detail.store_id) }}
          </el-descriptions-item>
          <el-descriptions-item label="来源汇总单">{{ detail.summary_id }}</el-descriptions-item>
          <el-descriptions-item label="司机">{{ detail.driver_id ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="车牌">{{ detail.plate_no || '—' }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTag(detail.status)" effect="light">
              {{ statusText(detail.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="发车时间">
            {{ formatDateTime(detail.loaded_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="签收时间">
            {{ formatDateTime(detail.signed_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">
            {{ formatDateTime(detail.created_at) }}
          </el-descriptions-item>
        </el-descriptions>

        <el-table
          :data="detailItems()"
          border
          stripe
          size="small"
          empty-text="暂无装车明细"
          style="margin-top: 14px"
        >
          <el-table-column label="SKU" min-width="160">
            <template #default="{ row }">{{ skuName(row.sku_id, row.sku_name) }}</template>
          </el-table-column>
          <el-table-column prop="batch_no" label="批次号" width="150" />
          <el-table-column label="发送数量" width="130" align="right">
            <template #default="{ row }">{{ formatQty(row.qty_base) }}</template>
          </el-table-column>
          <el-table-column label="来源分拣明细" width="140" align="right">
            <template #default="{ row }">{{ row.pick_item_id ?? '—' }}</template>
          </el-table-column>
        </el-table>
      </div>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 签收单查看：GET /signs/{id} -->
    <el-dialog v-model="signVisible" title="签收单详情" width="720px">
      <div v-loading="signLoading">
        <el-descriptions v-if="signDetail" :column="2" border size="small">
          <el-descriptions-item label="签收单号">{{ signDetail.id }}</el-descriptions-item>
          <el-descriptions-item label="签收状态">
            <el-tag :type="signDetail.status === 'full' ? 'success' : 'warning'" effect="light">
              {{ signStatusText(signDetail.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="签收时间">
            {{ formatDateTime(signDetail.sign_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="签收人">
            {{ signDetail.sign_by ?? '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="备注" :span="2">
            {{ signDetail.remark || '—' }}
          </el-descriptions-item>
        </el-descriptions>

        <el-table
          :data="signDetail?.items ?? []"
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
            <template #default="{ row }">
              <span :class="{ warn: Number(row.diff_qty_base) > 0 }">
                {{ formatQty(row.diff_qty_base) }}
              </span>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <template #footer>
        <el-button @click="signVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 生成配送单（装车）：POST /deliveries -->
    <el-dialog v-model="createVisible" title="生成配送单（装车）" width="880px" destroy-on-close>
      <el-form ref="createFormRef" :model="createForm" :rules="createRules" label-width="110px">
        <el-form-item label="要求日期" prop="require_date">
          <el-date-picker
            v-model="createForm.require_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择要求配送日期"
            style="width: 200px"
          />
        </el-form-item>
        <el-form-item label="配送门店" prop="store_id">
          <el-select
            v-model="createForm.store_id"
            filterable
            placeholder="选择门店"
            style="width: 320px"
          >
            <el-option
              v-for="s in stores"
              :key="s.id"
              :label="s.name + '（' + s.store_no + '）'"
              :value="s.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="司机 user_id" prop="driver_id">
          <el-input-number
            v-model="createForm.driver_id"
            :min="1"
            :precision="0"
            :controls="false"
            placeholder="司机 user_id"
            style="width: 200px"
          />
          <span class="hint">§8.2 未提供用户列表端点，司机按 user_id 指定</span>
        </el-form-item>
        <el-form-item label="车牌号" prop="plate_no">
          <el-input v-model="createForm.plate_no" maxlength="16" placeholder="如 鲁 G·8T216" style="width: 200px" />
        </el-form-item>
        <el-form-item label="来源汇总单" prop="summary_id">
          <el-input-number
            v-model="createForm.summary_id"
            :min="1"
            :precision="0"
            :controls="false"
            placeholder="汇总单 ID"
            style="width: 200px"
          />
          <span class="hint">§7.4 delivery.summary_id 为非空列，必填</span>
        </el-form-item>
      </el-form>

      <div class="sub-head">
        <span class="sub-title">装车明细</span>
        <span class="muted">SKU / 批次号 / 发送数量（基础单位）</span>
        <el-button type="primary" plain size="small" @click="addItemRow">添加一行</el-button>
      </div>

      <el-table :data="createForm.items" border stripe size="small" empty-text="请添加装车明细">
        <el-table-column label="SKU" min-width="220">
          <template #default="{ row }">
            <el-select v-model="row.sku_id" filterable placeholder="选择 SKU" style="width: 100%">
              <el-option
                v-for="s in skus"
                :key="s.id"
                :label="s.name + '（' + s.sku_no + '）'"
                :value="s.id"
              />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="批次号" width="180">
          <template #default="{ row }">
            <el-input v-model="row.batch_no" maxlength="32" placeholder="如 B20261013-01" />
          </template>
        </el-table-column>
        <el-table-column label="发送数量" width="160">
          <template #default="{ row }">
            <el-input-number v-model="row.qty_base" :min="0" :precision="3" :step="1" style="width: 100%" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" align="center">
          <template #default="{ $index }">
            <el-button link type="danger" @click="removeItemRow($index)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">生成配送单</el-button>
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
.page-head a {
  color: #6b6b6b;
  text-decoration: none;
  font-size: 14px;
  transition: color 0.2s;
}
.page-head a:hover {
  color: var(--nf-green);
}
/* 概览卡片：白卡 + 16px 圆角 + 柔和阴影 */
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
/* 表格卡片化：白色卡片 + 16px 圆角 + 柔和阴影，去掉默认描边 */
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
.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
.hint,
.muted {
  color: var(--nf-muted);
  font-size: 12px;
}
.sub-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 6px 0 10px;
}
.sub-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--nf-ink);
}
.warn {
  color: #e2604a;
  font-weight: 600;
}
@media (max-width: 900px) {
  .stat-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
