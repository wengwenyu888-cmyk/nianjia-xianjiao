<script setup lang="ts">
// 要货汇总（docs/02 §8.2「汇总分拣」）：
// 按配送日把当日 confirmed 要货单聚合成汇总单（一个配送日只落一张），
// 汇总只到 SKU 维度——"汇总看量、分拣落批次"（§7.3 summary_item 设计理由）。
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  generateSummary,
  listSummaries,
  type Summary,
  type SummaryStatus
} from '@/api/order'
import { getSkus, type Sku } from '@/api/store'

const router = useRouter()

// ---------- 基础工具 ----------

/** 日期偏移（YYYY-MM-DD） */
function dateOffset(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() + days)
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return String(d.getFullYear()) + '-' + month + '-' + day
}

/** 数量显示：最多 3 位小数、去掉多余 0（DECIMAL(14,3)；字符串/数字两种入参都接） */
function numText(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  return String(Number(n.toFixed(3)))
}

/** 汇总单状态显示（§7.4 summary.status） */
const SUMMARY_STATUS: Record<SummaryStatus, { text: string; type: 'info' | 'success' | 'warning' | 'danger' }> = {
  generated: { text: '已生成', type: 'info' },
  picking: { text: '分拣中', type: 'warning' },
  picked: { text: '已分拣', type: 'success' },
  delivering: { text: '配送中', type: 'warning' },
  done: { text: '已完成', type: 'success' }
}

function summaryStatusText(s: SummaryStatus | null | undefined): string {
  return s && SUMMARY_STATUS[s] ? SUMMARY_STATUS[s].text : '—'
}

function summaryStatusType(s: SummaryStatus | null | undefined): 'info' | 'success' | 'warning' | 'danger' {
  return s && SUMMARY_STATUS[s] ? SUMMARY_STATUS[s].type : 'info'
}

/** SKU 字典：SummaryItemOut 不返回名称/单位，页面用本地 SKU 列表解析 */
const skuOptions = ref<Sku[]>([])

async function loadSkuOptions(): Promise<void> {
  try {
    const res = await getSkus({ page: 1, page_size: 200 })
    skuOptions.value = res.list
  } catch {
    skuOptions.value = []
  }
}

/** SKU 展示名（后端未返回名称字段时本地解析，仍无则 SKU #id 兜底） */
function skuLabel(skuId: number): string {
  const hit = skuOptions.value.find((s) => s.id === skuId)
  return hit ? hit.sku_no + ' ' + hit.name : 'SKU #' + skuId
}

/** SKU 基础单位（汇总数量口径） */
function baseUnitOf(skuId: number): string {
  return skuOptions.value.find((s) => s.id === skuId)?.base_unit ?? '—'
}

/**
 * 涉及门店数：summary_item 表未存该列（后端当前不返回 store_count）。
 * 有任意一行带该字段时展示整列，都没有就整列隐藏，避免一排"—"占位。
 */
const hasStoreCount = computed<boolean>(() =>
  list.value.some((s) => (s.items ?? []).some((it) => it.store_count !== null && it.store_count !== undefined))
)

// ---------- 查询与生成 ----------

/** 配送日期：默认次日；清空表示查全部配送日 */
const requireDate = ref<string>(dateOffset(1))
const filterStatus = ref<SummaryStatus | ''>('')

const loading = ref(false)
const generating = ref(false)
const list = ref<Summary[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)

const emptyText = computed<string>(() =>
  requireDate.value ? '该配送日还没有汇总单，点「生成汇总」按已确认要货单聚合' : '暂无汇总单'
)

/** GET /summaries?require_date=&status= */
async function fetchList(): Promise<void> {
  loading.value = true
  try {
    const res = await listSummaries({
      require_date: requireDate.value || undefined,
      status: filterStatus.value || undefined,
      page: page.value,
      page_size: pageSize.value
    })
    list.value = res.list
    total.value = res.total
  } catch {
    // request.ts 已统一弹错；保证空态而不是残留旧数据
    list.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

/** POST /summaries/generate：按 require_date 汇总全部 confirmed 单（幂等，重复不会新建） */
async function handleGenerate(): Promise<void> {
  if (!requireDate.value) {
    ElMessage.warning('请先选择配送日期')
    return
  }
  try {
    await ElMessageBox.confirm(
      '将把 ' + requireDate.value + ' 的全部「已确认」要货单聚合成一张汇总单；同一配送日只落一张，重复生成不会新建。',
      '生成汇总',
      { type: 'warning', confirmButtonText: '生成汇总', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  generating.value = true
  try {
    const res = await generateSummary(requireDate.value)
    ElMessage.success('汇总单已生成：' + (res && res.summary_no ? res.summary_no : ''))
    page.value = 1
    await fetchList()
  } catch {
    // 40000（当日无已确认单）/ 40900（状态冲突）等由 request.ts 提示
  } finally {
    generating.value = false
  }
}

function handleSearch(): void {
  page.value = 1
  void fetchList()
}

function handleReset(): void {
  requireDate.value = dateOffset(1)
  filterStatus.value = ''
  page.value = 1
  void fetchList()
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

/** 生成分拣单：带着汇总单 id 与配送日跳 /picking（分拣按门店拆单） */
function goPicking(row: Summary): void {
  void router.push({
    path: '/picking',
    query: { summary_id: String(row.id), require_date: row.require_date }
  })
}

onMounted(() => {
  void fetchList()
  void loadSkuOptions()
})
</script>

<template>
  <div class="page">
    <div class="page-head glass-nav">
      <h2><span class="brand-name">念家鲜饺</span>要货汇总</h2>
      <router-link to="/">← 返回首页</router-link>
    </div>

    <el-card shadow="never" class="block">
      <div class="toolbar">
        <span class="label">配送日期</span>
        <el-date-picker
          v-model="requireDate"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="全部配送日"
          clearable
          style="width: 170px"
        />
        <el-select v-model="filterStatus" placeholder="全部状态" clearable style="width: 140px">
          <el-option label="已生成" value="generated" />
          <el-option label="分拣中" value="picking" />
          <el-option label="已分拣" value="picked" />
          <el-option label="配送中" value="delivering" />
          <el-option label="已完成" value="done" />
        </el-select>
        <el-button type="primary" @click="handleSearch">查询</el-button>
        <el-button @click="handleReset">重置</el-button>
        <el-button type="primary" plain :loading="generating" @click="handleGenerate">生成汇总</el-button>
      </div>
      <p class="tip">汇总只到 SKU 维度；批次分配在分拣环节落定（汇总看量、分拣落批次）。</p>
    </el-card>

    <el-card shadow="never" class="block">
      <template #header>
        <span class="card-title">汇总单</span>
      </template>

      <el-table v-loading="loading" :data="list" border>
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="detail">
              <p class="detail-note">
                按 SKU 汇总数量（基础单位）；批次分配在分拣环节落定（汇总看量、分拣落批次）。
              </p>
              <el-table :data="row.items || []" size="small" border>
                <el-table-column label="SKU" min-width="220">
                  <template #default="{ row: item }">{{ skuLabel(item.sku_id) }}</template>
                </el-table-column>
                <el-table-column label="汇总数量" width="150">
                  <template #default="{ row: item }">{{ numText(item.total_qty_base) }}</template>
                </el-table-column>
                <el-table-column label="单位(基础)" width="120">
                  <template #default="{ row: item }">{{ baseUnitOf(item.sku_id) }}</template>
                </el-table-column>
                <el-table-column v-if="hasStoreCount" label="涉及门店数" width="120">
                  <template #default="{ row: item }">
                    {{ item.store_count === null || item.store_count === undefined ? '—' : item.store_count }}
                  </template>
                </el-table-column>
                <template #empty>
                  <el-empty :image-size="60" description="该汇总单暂无明细（当日可能没有已确认的要货单）" />
                </template>
              </el-table>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="summary_no" label="汇总单号" width="200" />
        <el-table-column prop="require_date" label="配送日" width="130" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="summaryStatusType(row.status)" effect="light" size="small">
              {{ summaryStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="明细行数" width="100">
          <template #default="{ row }">
            {{ row.line_count || (row.items ? row.items.length : 0) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="goPicking(row as Summary)">生成分拣单</el-button>
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
.block {
  margin-bottom: 20px;
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
.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
</style>
