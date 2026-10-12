<script setup lang="ts">
// 报损：门店提交报损 + 总部审批（§8.2 报损端点，路径与方法逐字对齐）
//   POST /losses · GET /losses?store_id=&status= · POST /losses/{id}/approve
import { computed, onMounted, reactive, ref } from 'vue'
import dayjs from 'dayjs'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'

import {
  approveLoss,
  createLoss,
  listLosses,
  newIdempotencyKey,
  type Loss,
  type LossCreatePayload,
  type LossStatus,
  type LossType
} from '@/api/delivery'
import { getSkus, getStores, type Sku, type Store } from '@/api/store'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()

/**
 * 角色与数据范围（§8.1 / §8.2）：
 * - 提交报损 POST /losses 限 store_manager（数据范围限本店 user.store_id）
 * - 查报损与审批 GET /losses、POST /losses/{id}/approve 限 admin/ops
 */
const canCreate = computed(() => userStore.roleCodes.includes('store_manager'))
const canApprove = computed(() =>
  userStore.roleCodes.some((r) => r === 'admin' || r === 'ops')
)
const boundStoreId = computed<number | null>(() => userStore.user?.store_id ?? null)

// ---- 字典（§7.5 loss.type / loss.status） ----
const lossTypeOptions: {
  value: LossType
  label: string
  tag: 'warning' | 'danger' | 'info'
}[] = [
  { value: 'expire', label: '临期报损', tag: 'warning' },
  { value: 'damage', label: '破损', tag: 'danger' },
  { value: 'count_diff', label: '盘点差异', tag: 'info' }
]

const statusOptions: { value: LossStatus; label: string; tag: 'warning' | 'success' }[] = [
  { value: 'draft', label: '待审批', tag: 'warning' },
  { value: 'approved', label: '已审批', tag: 'success' }
]

function lossTypeText(v: LossType): string {
  return lossTypeOptions.find((it) => it.value === v)?.label ?? v
}

function lossTypeTag(v: LossType): 'warning' | 'danger' | 'info' {
  return lossTypeOptions.find((it) => it.value === v)?.tag ?? 'info'
}

function statusText(v: LossStatus): string {
  return statusOptions.find((it) => it.value === v)?.label ?? v
}

function statusTag(v: LossStatus): 'warning' | 'success' {
  return statusOptions.find((it) => it.value === v)?.tag ?? 'warning'
}

// ---- 格式化 ----
/** 数量：最多 3 位小数（§7 DECIMAL(14,3)） */
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

// ---- 主数据映射 ----
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
const list = ref<Loss[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

/** 查询条件：store_id 与 status 均为 §8.2 明确定义的参数 */
const query = reactive<{ store_id: number | undefined; status: LossStatus | '' }>({
  store_id: undefined,
  status: ''
})

/** 概览（当前页聚合） */
const stats = computed(() => {
  const rows = list.value
  return [
    { label: '报损单', value: String(rows.length) },
    { label: '待审批', value: String(rows.filter((r) => r.status === 'draft').length) },
    { label: '已审批', value: String(rows.filter((r) => r.status === 'approved').length) },
    {
      label: '报损数量合计',
      value: formatQty(rows.reduce((sum, r) => sum + Number(r.qty_base || 0), 0))
    }
  ]
})

async function fetchList(): Promise<void> {
  loading.value = true
  try {
    const res = await listLosses({
      page: page.value,
      page_size: pageSize.value,
      store_id: query.store_id,
      status: query.status || undefined
    })
    list.value = res?.list ?? []
    total.value = res?.total ?? 0
  } catch {
    // request.ts 已统一提示错误
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
  query.store_id = boundStoreId.value ?? undefined
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

/** el-table 插槽 row 为 DefaultRow，传给具体类型处理函数前显式收窄 */
function asLoss(row: unknown): Loss {
  return row as Loss
}

// ---- 提交报损（POST /losses，draft） ----
const createVisible = ref(false)
const creating = ref(false)
const createFormRef = ref<FormInstance>()
/** 本次提交的幂等键：失败重试复用，成功后重新生成（§7.5 loss.uk_idem） */
const createKey = ref(newIdempotencyKey())

const createForm = reactive<{
  store_id: number | undefined
  sku_id: number | undefined
  batch_no: string
  qty_base: number
  type: LossType
  reason: string
}>({
  store_id: undefined,
  sku_id: undefined,
  batch_no: '',
  qty_base: 1,
  type: 'expire',
  reason: ''
})

/** 表头校验：门店 / SKU / 类型必填（§7.5 loss 对应列为非空） */
const createRules: FormRules = {
  store_id: [{ required: true, message: '请选择报损门店', trigger: 'change' }],
  sku_id: [{ required: true, message: '请选择报损 SKU', trigger: 'change' }],
  type: [{ required: true, message: '请选择报损类型', trigger: 'change' }]
}

function openCreate(): void {
  createForm.store_id = boundStoreId.value ?? undefined
  createForm.sku_id = undefined
  createForm.batch_no = ''
  createForm.qty_base = 1
  createForm.type = 'expire'
  createForm.reason = ''
  createKey.value = newIdempotencyKey()
  createVisible.value = true
}

async function submitCreate(): Promise<void> {
  if (!createFormRef.value) return
  const valid = await createFormRef.value.validate().catch(() => false)
  if (!valid) return
  if (!(Number(createForm.qty_base) > 0)) {
    ElMessage.warning('报损数量需大于 0')
    return
  }
  creating.value = true
  try {
    const payload: LossCreatePayload = {
      store_id: Number(createForm.store_id),
      sku_id: Number(createForm.sku_id),
      batch_no: createForm.batch_no.trim() || null,
      qty_base: Number(createForm.qty_base),
      type: createForm.type,
      reason: createForm.reason.trim() || null
    }
    await createLoss(payload, createKey.value)
    ElMessage.success('报损单已提交，等待总部审批')
    createVisible.value = false
    await fetchList()
  } catch {
    // request.ts 已统一提示（幂等键重复返回 40900）
  } finally {
    creating.value = false
  }
}

// ---- 总部审批（POST /losses/{id}/approve） ----
const approvingId = ref<number | null>(null)

async function handleApprove(row: Loss): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '确认审批通过报损单 ' + row.loss_no + '？审批后将扣减门店批次库存并写入 batch_flow 流水。',
      '审批确认',
      { type: 'warning', confirmButtonText: '审批通过', cancelButtonText: '取消' }
    )
  } catch {
    return // 用户取消
  }
  approvingId.value = row.id
  try {
    await approveLoss(row.id)
    ElMessage.success('已审批：' + row.loss_no)
    await fetchList()
  } catch {
    // request.ts 已统一提示（非 draft 状态返回 40900）
  } finally {
    approvingId.value = null
  }
}

onMounted(async () => {
  query.store_id = boundStoreId.value ?? undefined
  await loadMasterData()
  await fetchList()
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2><span class="brand-name">念家鲜饺</span>报损管理</h2>
      <router-link to="/">← 返回首页</router-link>
    </div>

    <div class="stat-row">
      <div v-for="s in stats" :key="s.label" class="stat-card">
        <div class="stat-label">{{ s.label }}</div>
        <div class="stat-value">{{ s.value }}</div>
      </div>
    </div>

    <el-card shadow="never">
      <div class="toolbar">
        <el-select
          v-model="query.store_id"
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
        <el-select v-model="query.status" placeholder="全部状态" clearable style="width: 140px">
          <el-option
            v-for="it in statusOptions"
            :key="it.value"
            :label="it.label"
            :value="it.value"
          />
        </el-select>
        <el-button type="primary" @click="handleSearch">查询</el-button>
        <el-button @click="handleReset">重置</el-button>
        <el-button v-if="canCreate" type="primary" plain @click="openCreate">提交报损</el-button>
        <span v-if="!canCreate" class="hint">提交报损由门店店长发起（权限点 loss:create）</span>
      </div>

      <el-table v-loading="loading" :data="list" border stripe empty-text="暂无报损单">
        <el-table-column prop="loss_no" label="报损单号" width="180" />
        <el-table-column label="门店" min-width="160">
          <template #default="{ row }">{{ row.store_name || storeName(row.store_id) }}</template>
        </el-table-column>
        <el-table-column label="SKU" min-width="150">
          <template #default="{ row }">{{ skuName(row.sku_id, row.sku_name) }}</template>
        </el-table-column>
        <el-table-column label="批次号" width="150">
          <template #default="{ row }">{{ row.batch_no || '—' }}</template>
        </el-table-column>
        <el-table-column label="报损数量" width="120" align="right">
          <template #default="{ row }">{{ formatQty(row.qty_base) }}</template>
        </el-table-column>
        <el-table-column label="类型" width="110">
          <template #default="{ row }">
            <el-tag :type="lossTypeTag(row.type)" effect="light">
              {{ lossTypeText(row.type) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="原因" min-width="160">
          <template #default="{ row }">{{ row.reason || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status)" effect="light">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="提交时间" width="150">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="审批时间" width="150">
          <template #default="{ row }">{{ formatDateTime(row.approved_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="canApprove && row.status === 'draft'"
              link
              type="primary"
              :loading="approvingId === row.id"
              @click="handleApprove(asLoss(row))"
            >
              审批通过
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
    </el-card>

    <!-- 提交报损：POST /losses -->
    <el-dialog v-model="createVisible" title="提交报损" width="620px" destroy-on-close>
      <el-form ref="createFormRef" :model="createForm" :rules="createRules" label-width="100px">
        <el-form-item label="报损门店" prop="store_id">
          <el-select
            v-model="createForm.store_id"
            filterable
            :disabled="boundStoreId !== null"
            placeholder="选择门店"
            style="width: 100%"
          >
            <el-option
              v-for="s in stores"
              :key="s.id"
              :label="s.name + '（' + s.store_no + '）'"
              :value="s.id"
            />
          </el-select>
          <span v-if="boundStoreId !== null" class="hint">门店账号数据范围限本店（§8.1）</span>
        </el-form-item>
        <el-form-item label="SKU" prop="sku_id">
          <el-select v-model="createForm.sku_id" filterable placeholder="选择 SKU" style="width: 100%">
            <el-option
              v-for="s in skus"
              :key="s.id"
              :label="s.name + '（' + s.sku_no + '）'"
              :value="s.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="批次号" prop="batch_no">
          <el-input v-model="createForm.batch_no" maxlength="32" placeholder="如 B20261013-01（可留空）" />
        </el-form-item>
        <el-form-item label="报损数量" prop="qty_base">
          <el-input-number v-model="createForm.qty_base" :min="0" :precision="3" :step="1" style="width: 200px" />
          <span class="hint">基础单位；挂批次保证库存去向可解释（§7.5）</span>
        </el-form-item>
        <el-form-item label="报损类型" prop="type">
          <el-select v-model="createForm.type" placeholder="选择类型" style="width: 200px">
            <el-option
              v-for="it in lossTypeOptions"
              :key="it.value"
              :label="it.label"
              :value="it.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="原因说明" prop="reason">
          <el-input
            v-model="createForm.reason"
            type="textarea"
            :rows="3"
            maxlength="255"
            show-word-limit
            placeholder="如：冷柜温度异常导致馅料临期"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">提交报损</el-button>
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
@media (max-width: 900px) {
  .stat-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
