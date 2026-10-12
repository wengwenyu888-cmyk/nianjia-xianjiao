<script setup lang="ts">
// 分拣管理（docs/02 §8.2「汇总分拣」+「智能体」pick-plan）
// 契约来源：backend/app/schema/summary.py（PickOut/PickItemOut）+ backend/app/schema/agent.py（PickPlanOut）。
// 业务：一张汇总单按门店拆多张分拣单；批次在此落定（FIFO 按 expire_at 升序扣减并写 batch_flow 流水）。
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { getPickPlan, type PickPlan, type PickPlanTask } from '@/api/agent'
import {
  completePick,
  createPick,
  listPicks,
  listSummaries,
  type PickItem,
  type PickOrder,
  type PickStatus,
  type Summary
} from '@/api/order'
import { getSkus, getStores, type Sku, type Store } from '@/api/store'

const route = useRoute()

// ---------- 基础工具 ----------

function dateOffset(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() + days)
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return String(d.getFullYear()) + '-' + month + '-' + day
}

/**
 * 数量显示：最多 3 位小数、去掉多余 0。
 * 分拣明细/预演里的数量是字符串（Decimal → str），两种入参都接。
 */
function numText(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  return String(Number(n.toFixed(3)))
}

/** 分拣单状态显示（§7.4 pick.status） */
const PICK_STATUS: Record<PickStatus, { text: string; type: 'info' | 'success' | 'warning' | 'danger' }> = {
  created: { text: '待分拣', type: 'info' },
  picking: { text: '分拣中', type: 'warning' },
  done: { text: '已完成', type: 'success' },
  cancelled: { text: '已取消', type: 'danger' }
}

function pickStatusText(s: PickStatus | null | undefined): string {
  return s && PICK_STATUS[s] ? PICK_STATUS[s].text : '—'
}

function pickStatusType(s: PickStatus | null | undefined): 'info' | 'success' | 'warning' | 'danger' {
  return s && PICK_STATUS[s] ? PICK_STATUS[s].type : 'info'
}

/** FIFO 排序键：按批次到期日升序，无到期日的排最后 */
function expireKey(it: PickItem): string {
  return it.expire_at ? String(it.expire_at) : '9999-12-31'
}

/**
 * 分拣明细展示顺序：后端按 FIFO 分配顺序返回（到期日升序取批），
 * 若后端补上 expire_at 字段，这里再按到期日显式排序，保证"先到期先出"在页面上可见。
 */
function fifoRows(items: PickItem[] | undefined): PickItem[] {
  const rows = (items ?? []).slice()
  rows.sort((a, b) => expireKey(a).localeCompare(expireKey(b)))
  return rows
}

// ---------- 主数据字典（接口不返回名称字段，页面本地解析） ----------

const skuOptions = ref<Sku[]>([])
const storeOptions = ref<Store[]>([])

/** SKU 展示名 */
function skuLabel(skuId: number): string {
  const hit = skuOptions.value.find((s) => s.id === skuId)
  return hit ? hit.sku_no + ' ' + hit.name : 'SKU #' + skuId
}

/** SKU 基础单位（分拣数量口径） */
function baseUnitOf(skuId: number): string {
  return skuOptions.value.find((s) => s.id === skuId)?.base_unit ?? '—'
}

/** 门店展示名 */
function storeLabel(storeId: number): string {
  const hit = storeOptions.value.find((s) => s.id === storeId)
  return hit ? hit.name : '门店 #' + storeId
}

async function loadDictionaries(): Promise<void> {
  try {
    const res = await getSkus({ page: 1, page_size: 200 })
    skuOptions.value = res.list
  } catch {
    skuOptions.value = []
  }
  try {
    const res = await getStores({ page: 1, page_size: 200 })
    storeOptions.value = res.list
  } catch {
    storeOptions.value = []
  }
}

// ---------- 列表（GET /picks：后端读端点待补，页面已降级） ----------

const filterDate = ref<string>(dateOffset(1))
const filterStatus = ref<PickStatus | ''>('')

const loading = ref(false)
/** 列表接口不可用（后端未实现 GET /picks）时给行内提示，不影响生成/完成动作 */
const listError = ref(false)
const list = ref<PickOrder[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)

/** 汇总单字典：用于把 pick.summary_id 显示成单号 + 配送日（PickOut 不返回这两个字段） */
const summaryOptions = ref<Summary[]>([])

function summaryLabel(summaryId: number): string {
  const hit = summaryOptions.value.find((s) => s.id === summaryId)
  return hit ? hit.summary_no : '#' + summaryId
}

function summaryDate(summaryId: number): string {
  const hit = summaryOptions.value.find((s) => s.id === summaryId)
  return hit ? hit.require_date : '—'
}

const emptyText = computed<string>(() =>
  filterDate.value ? '该配送日暂无分拣单：先在上方「新建分拣单」按门店拆单' : '暂无分拣单'
)

async function loadSummaryOptions(): Promise<void> {
  try {
    const res = await listSummaries({
      require_date: filterDate.value || undefined,
      page: 1,
      page_size: 100
    })
    summaryOptions.value = res.list
  } catch {
    summaryOptions.value = []
  }
}

async function fetchList(): Promise<void> {
  loading.value = true
  listError.value = false
  try {
    const res = await listPicks({
      require_date: filterDate.value || undefined,
      status: filterStatus.value || undefined,
      page: page.value,
      page_size: pageSize.value
    })
    list.value = res.list
    total.value = res.total
  } catch {
    // request.ts 已统一弹错；这里置空并给出行内说明（GET /picks 后端可能尚未开放）
    list.value = []
    total.value = 0
    listError.value = true
  } finally {
    loading.value = false
  }
}

/** 列表 + 汇总单字典一起刷新（配送日变化后字典要跟着换） */
async function refresh(): Promise<void> {
  await Promise.all([fetchList(), loadSummaryOptions()])
}

function handleSearch(): void {
  page.value = 1
  void refresh()
}

function handleReset(): void {
  filterDate.value = dateOffset(1)
  filterStatus.value = ''
  page.value = 1
  void refresh()
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

// ---------- 新建分拣单（POST /picks） ----------

const dialogVisible = ref(false)
const creating = ref(false)
/** 从汇总页跳转带过来的汇总单 id（「生成分拣单」入口） */
const pendingSummaryId = ref<number | null>(null)
const form = ref<{ summary_id: number | null; store_id: number | null }>({
  summary_id: null,
  store_id: null
})

/** 打开对话框：按当前配送日载入可选汇总单与门店 */
async function openCreate(): Promise<void> {
  await loadSummaryOptions()
  if (storeOptions.value.length === 0) await loadDictionaries()
  form.value = { summary_id: pendingSummaryId.value, store_id: null }
  if (form.value.summary_id === null && summaryOptions.value.length > 0) {
    form.value.summary_id = summaryOptions.value[0].id
  }
  dialogVisible.value = true
}

async function submitCreate(): Promise<void> {
  if (!form.value.summary_id) {
    ElMessage.warning('请选择汇总单')
    return
  }
  if (!form.value.store_id) {
    ElMessage.warning('请选择门店')
    return
  }
  creating.value = true
  try {
    const pick = await createPick({ summary_id: form.value.summary_id, store_id: form.value.store_id })
    ElMessage.success('分拣单 ' + pick.pick_no + ' 已生成（同事务锁批次扣库存）')
    dialogVisible.value = false
    pendingSummaryId.value = null
    page.value = 1
    await refresh()
  } catch {
    // 40900（同店重复生成 / 库存不足）等由 request.ts 提示
  } finally {
    creating.value = false
  }
}

// ---------- 完成分拣（POST /picks/{id}/complete） ----------

const completingId = ref<number | null>(null)

async function handleComplete(row: PickOrder): Promise<void> {
  if (row.status === 'done') {
    ElMessage.info('该分拣单已完成')
    return
  }
  try {
    await ElMessageBox.confirm(
      '完成后批次扣减与 batch_flow 流水不可回退。',
      '完成分拣（' + row.pick_no + '）',
      { type: 'warning', confirmButtonText: '完成分拣', cancelButtonText: '返回' }
    )
  } catch {
    return
  }
  completingId.value = row.id
  try {
    await completePick(row.id)
    ElMessage.success('分拣已完成')
    await fetchList()
  } catch {
    // 状态冲突 / 库存异常等由 request.ts 提示
  } finally {
    completingId.value = null
  }
}

// ---------- FIFO 批次预演（POST /agent/pick-plan，只读） ----------

const planVisible = ref(false)
const planLoading = ref(false)
const planError = ref(false)
const plan = ref<PickPlan | null>(null)

const planTasks = computed<PickPlanTask[]>(() => plan.value?.tasks ?? [])
const planWarnings = computed<string[]>(() => plan.value?.warnings ?? [])
/** 预演摘要：策略 + 生成时间 + 需求/缺口合计 */
const planInfo = computed<string>(() => {
  const p = plan.value
  if (!p) return ''
  return (
    '策略 ' +
    p.policy +
    ' · 生成于 ' +
    p.generated_at +
    ' · 需求合计 ' +
    numText(p.total_required_qty_base) +
    ' · 预演缺口 ' +
    numText(p.total_shortage_qty_base) +
    '（基础单位）'
  )
})

async function handlePlan(): Promise<void> {
  if (!filterDate.value) {
    ElMessage.warning('请先选择配送日期，再做批次预演')
    return
  }
  planVisible.value = true
  planLoading.value = true
  planError.value = false
  plan.value = null
  try {
    // 只读预演：不锁行、不扣结存、不写流水（只落一条 pick_plan 建议快照）
    plan.value = await getPickPlan({ require_date: filterDate.value })
  } catch {
    planError.value = true
  } finally {
    planLoading.value = false
  }
}

onMounted(async () => {
  const qDate = typeof route.query.require_date === 'string' ? route.query.require_date : ''
  if (qDate) filterDate.value = qDate
  const rawSummary = typeof route.query.summary_id === 'string' ? route.query.summary_id : ''
  const parsedSummary = rawSummary ? Number(rawSummary) : NaN
  if (!Number.isNaN(parsedSummary)) {
    pendingSummaryId.value = parsedSummary
    ElMessage.info('已带上汇总单 #' + parsedSummary + '，点「新建分拣单」按门店拆单')
  }
  await loadDictionaries()
  await refresh()
})
</script>

<template>
  <div class="page">
    <div class="page-head glass-nav">
      <h2><span class="brand-name">念家鲜饺</span>分拣管理</h2>
      <router-link to="/">← 返回首页</router-link>
    </div>

    <el-card shadow="never" class="block">
      <div class="toolbar">
        <span class="label">配送日期</span>
        <el-date-picker
          v-model="filterDate"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="全部配送日"
          clearable
          style="width: 170px"
        />
        <el-select v-model="filterStatus" placeholder="全部状态" clearable style="width: 140px">
          <el-option label="待分拣" value="created" />
          <el-option label="分拣中" value="picking" />
          <el-option label="已完成" value="done" />
          <el-option label="已取消" value="cancelled" />
        </el-select>
        <el-button type="primary" @click="handleSearch">查询</el-button>
        <el-button @click="handleReset">重置</el-button>
        <el-button type="primary" plain :disabled="!filterDate" @click="openCreate">新建分拣单</el-button>
        <el-button :disabled="!filterDate" @click="handlePlan">FIFO 批次预演</el-button>
      </div>
      <p class="tip">分拣按门店拆单，批次按到期日升序（FIFO）扣减；明细展示实际拣出的批次号。</p>
    </el-card>

    <el-card shadow="never" class="block">
      <template #header>
        <span class="card-title">分拣单</span>
      </template>

      <el-alert
        v-if="listError"
        type="warning"
        :closable="false"
        show-icon
        title="分拣单列表加载失败"
        description="后端 GET /picks 读端点可能尚未开放（§8.2 只列了 POST /picks 与完成分拣）；新建分拣单与完成分拣不受影响。"
        class="block-gap"
      />

      <el-table v-loading="loading" :data="list" border>
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="detail">
              <p class="detail-note">
                明细按 FIFO 分配顺序展示（先进先出、批次在此落定），批次号贯穿配送与签收环节。
              </p>
              <el-table :data="fifoRows(row.items)" size="small" border>
                <el-table-column label="SKU" min-width="200">
                  <template #default="{ row: item }">{{ skuLabel(item.sku_id) }}</template>
                </el-table-column>
                <el-table-column label="批次号" width="200">
                  <template #default="{ row: item }">{{ item.batch_no || '—' }}</template>
                </el-table-column>
                <el-table-column label="拣出数量" width="140">
                  <template #default="{ row: item }">{{ numText(item.qty_base) }}</template>
                </el-table-column>
                <el-table-column label="单位(基础)" width="120">
                  <template #default="{ row: item }">{{ baseUnitOf(item.sku_id) }}</template>
                </el-table-column>
                <template #empty>
                  <el-empty :image-size="60" description="该分拣单暂无明细" />
                </template>
              </el-table>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="pick_no" label="分拣单号" width="180" />
        <el-table-column label="门店" min-width="150">
          <template #default="{ row }">{{ storeLabel(row.store_id) }}</template>
        </el-table-column>
        <el-table-column label="汇总单" width="180">
          <template #default="{ row }">{{ summaryLabel(row.summary_id) }}</template>
        </el-table-column>
        <el-table-column label="配送日" width="120">
          <template #default="{ row }">{{ summaryDate(row.summary_id) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="pickStatusType(row.status)" effect="light" size="small">
              {{ pickStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="明细行数" width="100">
          <template #default="{ row }">
            {{ row.items && row.items.length > 0 ? row.items.length : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status !== 'done' && row.status !== 'cancelled'"
              link
              type="primary"
              :loading="completingId === row.id"
              @click="handleComplete(row as PickOrder)"
            >
              完成分拣
            </el-button>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :image-size="80" :description="emptyText" />
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

    <!-- 新建分拣单：按门店生成 -->
    <el-dialog v-model="dialogVisible" title="新建分拣单" width="580px" destroy-on-close>
      <el-form label-width="100px">
        <el-form-item label="配送日期">
          <span class="form-text">{{ filterDate || '全部配送日' }}</span>
        </el-form-item>
        <el-form-item label="汇总单">
          <el-select v-model="form.summary_id" placeholder="选择汇总单" style="width: 100%">
            <el-option
              v-for="s in summaryOptions"
              :key="s.id"
              :label="s.summary_no + '（' + s.require_date + '）'"
              :value="s.id"
            />
          </el-select>
          <span v-if="summaryOptions.length === 0" class="hint">该配送日暂无汇总单，请先到「要货汇总」生成</span>
        </el-form-item>
        <el-form-item label="门店">
          <el-select v-model="form.store_id" filterable placeholder="选择门店" style="width: 100%">
            <el-option
              v-for="s in storeOptions"
              :key="s.id"
              :label="s.name + '（' + s.store_no + '）'"
              :value="s.id"
            />
          </el-select>
          <span v-if="storeOptions.length === 0" class="hint">门店列表未加载，请确认后端 /stores 可用</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">生成分拣单</el-button>
      </template>
    </el-dialog>

    <!-- FIFO 批次预演：只读，不落库存（POST /agent/pick-plan） -->
    <el-dialog v-model="planVisible" title="FIFO 批次预演（只读）" width="960px">
      <el-alert
        v-if="planError"
        type="error"
        :closable="false"
        show-icon
        title="预演失败"
        description="预演只读、不影响库存；可确认后端 /agent/pick-plan 可用后重试。"
      />
      <template v-else>
        <p v-if="planInfo" class="detail-note">{{ planInfo }}</p>
        <el-alert
          v-for="(w, wi) in planWarnings"
          :key="'pw-' + wi"
          type="info"
          :closable="false"
          show-icon
          :title="w"
          class="block-gap"
        />
        <el-table v-loading="planLoading" :data="planTasks" border size="small">
          <el-table-column label="门店" min-width="140">
            <template #default="{ row }">{{ storeLabel(row.store_id) }}</template>
          </el-table-column>
          <el-table-column label="SKU" min-width="170">
            <template #default="{ row }">{{ skuLabel(row.sku_id) }}</template>
          </el-table-column>
          <el-table-column label="需求量" width="110">
            <template #default="{ row }">{{ numText(row.required_qty_base) }}</template>
          </el-table-column>
          <el-table-column label="预演可分配" width="120">
            <template #default="{ row }">{{ numText(row.allocated_qty_base) }}</template>
          </el-table-column>
          <el-table-column label="缺口" width="100">
            <template #default="{ row }">
              <span :class="{ 'danger-text': Number(row.shortage_qty_base) > 0 }">
                {{ numText(row.shortage_qty_base) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="FIFO 批次（到期日升序）" min-width="260">
            <template #default="{ row }">
              <div v-for="b in row.batches || []" :key="b.batch_no" class="batch-line">
                <span class="batch-no">{{ b.batch_no }}</span>
                <span>{{ numText(b.qty_base) }}</span>
                <span class="muted">{{ b.expire_at || '无到期日' }}</span>
              </div>
              <span v-if="!row.batches || row.batches.length === 0" class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="提示" min-width="180">
            <template #default="{ row }">
              <span v-if="row.flags && row.flags.length > 0" class="flags-text">
                {{ (row.flags || []).join('；') }}
              </span>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty :image-size="60" description="暂无预演结果（当日可能还没有已确认要货单）" />
          </template>
        </el-table>
      </template>
      <template #footer>
        <el-button type="primary" @click="planVisible = false">知道了</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
}
/* 顶部毛玻璃导航条：.glass-nav 提供半透明与模糊 */
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
/* 页面标题：24px / 800（docs/07 §3） */
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
.muted {
  color: var(--nf-muted);
  font-size: 13px;
}
.block {
  margin-bottom: 20px;
}
.block-gap {
  margin-bottom: 12px;
}
.card-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--nf-ink);
}
.toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
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
.form-text {
  font-size: 14px;
  color: var(--nf-ink);
}
.hint {
  margin-left: 8px;
  color: #909399;
  font-size: 12px;
}
/* 展开明细：奶油白浅底分区，和主表拉开层次 */
.detail {
  padding: 14px 18px;
  border-radius: 12px;
  background: #fbf8f0;
}
.detail-note {
  margin: 0 0 10px;
  font-size: 13px;
  color: var(--nf-muted);
}
/* 批次行：预演明细按行铺开，批号用等宽感强调 */
.batch-line {
  display: flex;
  gap: 10px;
  align-items: baseline;
  font-size: 13px;
}
.batch-no {
  font-weight: 600;
  color: var(--nf-deep);
}
.flags-text {
  font-size: 12px;
  color: #b7791f;
}
.danger-text {
  color: #e2604a;
  font-weight: 600;
}
.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
</style>
