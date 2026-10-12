<script setup lang="ts">
// 采购管理（docs/02 §7.2 采购单 + 收货入库；§8.2 采购端点）
//   POST /purchase-orders · GET /purchase-orders?supplier_id=&status= · POST /purchase-orders/{id}/receive
// 收货由后端在同一事务内「生成批次库存 batch_stock + 写批次流水 batch_flow(receive_add)」；
// 批次在这一步落定，后续分拣 / 配送 / 报损都按批次追溯。
import { computed, onMounted, reactive, ref } from 'vue'
import dayjs from 'dayjs'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'

import { newIdempotencyKey } from '@/api/order'
import {
  createPurchaseOrder,
  listPurchaseOrders,
  receivePurchaseOrder,
  type PurchaseOrder,
  type PurchaseOrderItem,
  type PurchaseOrderItemPayload,
  type PurchaseOrderStatus,
  type PurchaseReceiveItemPayload
} from '@/api/purchase'
import { getSkus, getSuppliers, type Sku, type Supplier } from '@/api/store'

// ---------- 格式化 ----------

/** 金额：千分位 + 两位小数（后端 DECIMAL 可能下发字符串，统一 Number 归一） */
function formatMoney(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return '¥' + n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** 数量：最多 3 位小数（§7 DECIMAL(14,3)） */
function formatQty(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 3 })
}

/** 日期：ISO8601 → YYYY-MM-DD（预计到货日按日期口径） */
function formatDate(v: string | null | undefined): string {
  if (!v) return '—'
  const d = dayjs(v)
  return d.isValid() ? d.format('YYYY-MM-DD') : v
}

/** 单价归一：留空/非正数 = undefined（省略该字段，后端按价目表现行价定价；后端校验 unit_price > 0） */
function priceOrUndefined(v: number | string | null | undefined): number | undefined {
  if (v === null || v === undefined || String(v).trim() === '') return undefined
  const n = Number(v)
  return Number.isFinite(n) && n > 0 ? n : undefined
}

// ---------- 状态字典（§7.2 purchase_order.status） ----------

const PO_STATUS: {
  value: PurchaseOrderStatus
  label: string
  tag: 'warning' | 'success' | 'info'
}[] = [
  { value: 'draft', label: '待收货', tag: 'warning' },
  // 后端状态机为 draft→submitted→received：submitted 同样可收货，与 draft 并列展示
  { value: 'submitted', label: '已提交', tag: 'warning' },
  { value: 'received', label: '已收货', tag: 'success' },
  { value: 'cancelled', label: '已取消', tag: 'info' }
]

function poStatusText(v: PurchaseOrderStatus | string): string {
  return PO_STATUS.find((it) => it.value === v)?.label ?? v
}

function poStatusTag(v: PurchaseOrderStatus | string): 'warning' | 'success' | 'info' {
  return PO_STATUS.find((it) => it.value === v)?.tag ?? 'info'
}

// ---------- 主数据字典（后端 Out 已带 supplier_name/sku_no/sku_name，缺失时才回退） ----------

const suppliers = ref<Supplier[]>([])
const skus = ref<Sku[]>([])
const supplierMap = computed(() => new Map(suppliers.value.map((s) => [s.id, s])))
const skuMap = computed(() => new Map(skus.value.map((s) => [s.id, s])))

/** 供应商展示：优先后端 supplier_name，缺失回退本地字典 */
function supplierText(id: number, name?: string | null): string {
  if (name) return name
  const hit = supplierMap.value.get(id)
  return hit ? hit.name : '供应商#' + id
}

/** SKU 展示：优先后端 sku_no/sku_name，缺失回退本地字典 */
function skuText(skuId: number, skuNo?: string | null, skuName?: string | null): string {
  const hit = skuMap.value.get(skuId)
  const no = skuNo || hit?.sku_no || 'SKU#' + skuId
  const name = skuName || hit?.name || ''
  return name ? no + ' ' + name : no
}

/** 订货单位（sku.unit）：新建明细里随行展示，便于确认换算口径 */
function skuUnit(skuId: number | null | undefined): string {
  if (!skuId) return '—'
  return skuMap.value.get(skuId)?.unit || '—'
}

/** 明细单位：行内 unit 优先，缺失回退本地 SKU 字典 */
function unitText(item: { sku_id: number; unit?: string | null }): string {
  return item.unit || skuMap.value.get(item.sku_id)?.unit || '—'
}

/** el-table 插槽 row 为 DefaultRow，传给具体类型处理函数前显式收窄 */
function asPurchaseOrder(row: unknown): PurchaseOrder {
  return row as PurchaseOrder
}

async function loadDictionaries(): Promise<void> {
  const [supplierRes, skuRes] = await Promise.allSettled([
    getSuppliers({ page: 1, page_size: 200 }),
    getSkus({ page: 1, page_size: 200 })
  ])
  if (supplierRes.status === 'fulfilled') suppliers.value = supplierRes.value?.list ?? []
  if (skuRes.status === 'fulfilled') skus.value = skuRes.value?.list ?? []
}

// ---------- 列表（GET /purchase-orders） ----------

const loading = ref(false)
const list = ref<PurchaseOrder[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

/** 查询条件：供应商 + 状态（§8.2 明确定义的参数） */
const query = reactive<{ supplier_id: number | undefined; status: PurchaseOrderStatus | '' }>({
  supplier_id: undefined,
  status: ''
})

async function fetchList(): Promise<void> {
  loading.value = true
  try {
    const res = await listPurchaseOrders({
      page: page.value,
      page_size: pageSize.value,
      supplier_id: query.supplier_id,
      status: query.status || undefined
    })
    list.value = res?.list ?? []
    total.value = res?.total ?? 0
  } catch {
    // request.ts 已统一提示错误；这里置空保证页面可用
    list.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function handleSearch(): void {
  page.value = 1
  void fetchList()
}

function handleReset(): void {
  query.supplier_id = undefined
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

// ---------- 查看明细（列表已随行返回 items，无需详情端点） ----------

const detailVisible = ref(false)
const detail = ref<PurchaseOrder | null>(null)
const detailItems = computed<PurchaseOrderItem[]>(() => detail.value?.items ?? [])

function openDetail(row: PurchaseOrder): void {
  detail.value = row
  detailVisible.value = true
}

// ---------- 新建采购单（POST /purchase-orders，幂等） ----------

/** 明细行：SKU 单选 + 订货数量 + 单价（可空 = 取价目表） */
interface ItemRow {
  sku_id: number | null
  qty_unit: number
  unit_price: number | null
}

const createVisible = ref(false)
const creating = ref(false)
const createFormRef = ref<FormInstance>()
/** 本次提交的幂等键：失败重试复用，成功后重新生成（§7.2 purchase_order.uk_idem） */
const createKey = ref(newIdempotencyKey())

const createForm = reactive<{
  supplier_id: number | undefined
  expected_date: string
  remark: string
  items: ItemRow[]
}>({
  supplier_id: undefined,
  expected_date: '',
  remark: '',
  items: []
})

/** 表头校验：供应商必选（§7.2 purchase_order.supplier_id 非空列） */
const createRules: FormRules = {
  supplier_id: [{ required: true, message: '请选择供应商', trigger: 'change' }]
}

function emptyItemRow(): ItemRow {
  return { sku_id: null, qty_unit: 1, unit_price: null }
}

function addItemRow(): void {
  createForm.items.push(emptyItemRow())
}

function removeItemRow(index: number): void {
  createForm.items.splice(index, 1)
}

function openCreate(): void {
  createForm.supplier_id = undefined
  createForm.expected_date = ''
  createForm.remark = ''
  createForm.items = [emptyItemRow()]
  createKey.value = newIdempotencyKey()
  createVisible.value = true
}

/** 明细逐行校验（动态行不用 el-form rules，避免下标耦合） */
function itemRowError(): string | null {
  if (createForm.items.length === 0) return '请至少添加一条采购明细'
  const seen = new Set<number>()
  for (let i = 0; i < createForm.items.length; i += 1) {
    const row = createForm.items[i]
    const at = '第 ' + (i + 1) + ' 行：'
    if (row.sku_id === null) return at + '请选择 SKU'
    if (seen.has(Number(row.sku_id))) return at + 'SKU 重复，请合并为一行'
    seen.add(Number(row.sku_id))
    if (!(Number(row.qty_unit) > 0)) return at + '订货数量需大于 0'
    const price = priceOrUndefined(row.unit_price)
    if (String(row.unit_price ?? '').trim() !== '' && price === undefined) {
      return at + '单价需大于 0（留空 = 取价目表）'
    }
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
    const items: PurchaseOrderItemPayload[] = createForm.items.map((row) => {
      const sku = skuMap.value.get(Number(row.sku_id))
      return {
        sku_id: Number(row.sku_id),
        qty_unit: Number(row.qty_unit),
        // 订货单位随行下发，保证后端换算口径与页面选择一致
        unit: sku?.unit,
        unit_price: priceOrUndefined(row.unit_price)
      }
    })
    const po = await createPurchaseOrder(
      {
        supplier_id: Number(createForm.supplier_id),
        expected_date: createForm.expected_date || null,
        remark: createForm.remark.trim() || null,
        items
      },
      createKey.value
    )
    ElMessage.success('采购单 ' + po.po_no + ' 已创建')
    createVisible.value = false
    createKey.value = newIdempotencyKey()
    page.value = 1
    await fetchList()
  } catch {
    // request.ts 已统一提示（重复幂等键返回首次结果 / 参数校验失败）
  } finally {
    creating.value = false
  }
}

// ---------- 收货入库（POST /purchase-orders/{id}/receive） ----------

/** 收货明细行：默认按采购单全量，可改；数量口径为基础单位 */
interface ReceiveRow {
  sku_id: number
  sku_no?: string | null
  sku_name?: string | null
  unit: string
  /** 采购单订货量（只读展示） */
  qty_unit: number
  /** 本次可收量（基础单位）= 订购量 − 已收量；用于「全量」复位与默认值 */
  full_base: number
  /** 本次收货数量（基础单位） */
  qty_base: number
  /** 采购单行单价，> 0 时随收货回传 */
  unit_price: number
}

const receiveVisible = ref(false)
const receiving = ref(false)
const receiveTarget = ref<PurchaseOrder | null>(null)

const receiveForm = reactive<{
  batch_no_prefix: string
  expire_at: string
  rows: ReceiveRow[]
}>({
  batch_no_prefix: '',
  expire_at: '',
  rows: []
})

function openReceive(row: PurchaseOrder): void {
  if (row.status !== 'draft' && row.status !== 'submitted') {
    ElMessage.info('该采购单不是待收货状态')
    return
  }
  receiveTarget.value = row
  receiveForm.batch_no_prefix = ''
  receiveForm.expire_at = ''
  receiveForm.rows = (row.items ?? []).map((it) => {
    // 本次可收量 = 订购量 − 已收量：分批收货时若按整单量预填，第二次收货会把整单量重复入账
    const receivable = Number(it.qty_base) - Number(it.received_qty_base ?? 0)
    const safe = Number.isFinite(receivable) && receivable > 0 ? receivable : 0
    return {
      sku_id: it.sku_id,
      sku_no: it.sku_no ?? null,
      sku_name: it.sku_name ?? null,
      unit: it.unit,
      qty_unit: Number(it.qty_unit),
      full_base: safe,
      qty_base: safe,
      unit_price: Number(it.unit_price)
    }
  })
  receiveVisible.value = true
}

/** 复位为「本次可收量」（订购量 − 已收量） */
function resetReceiveRow(index: number): void {
  const row = receiveForm.rows[index]
  if (row) row.qty_base = row.full_base
}

async function submitReceive(): Promise<void> {
  const target = receiveTarget.value
  if (!target) return
  if (!receiveForm.expire_at) {
    ElMessage.warning('请选择保质期至（必填，批次临期预警依据）')
    return
  }
  for (let i = 0; i < receiveForm.rows.length; i += 1) {
    const qty = Number(receiveForm.rows[i].qty_base)
    if (!(qty >= 0)) {
      ElMessage.warning('第 ' + (i + 1) + ' 行：收货数量不能为负')
      return
    }
  }
  if (receiveForm.rows.length > 0 && !receiveForm.rows.some((r) => Number(r.qty_base) > 0)) {
    ElMessage.warning('至少一行收货数量需大于 0')
    return
  }
  // 明细缺省 = 按采购单明细全量收货：列表未返回明细时省略 items，交由后端全量入账
  const items: PurchaseReceiveItemPayload[] | undefined =
    receiveForm.rows.length > 0
      ? receiveForm.rows
          .filter((r) => Number(r.qty_base) > 0)
          .map((r) => ({
            sku_id: r.sku_id,
            qty_base: Number(r.qty_base),
            expire_at: receiveForm.expire_at,
            unit_price: r.unit_price > 0 ? r.unit_price : undefined
          }))
      : undefined
  receiving.value = true
  try {
    await receivePurchaseOrder(target.id, {
      batch_no_prefix: receiveForm.batch_no_prefix.trim() || undefined,
      expire_at: receiveForm.expire_at,
      items
    })
    ElMessage.success('采购单 ' + target.po_no + ' 已入库并写入批次流水')
    receiveVisible.value = false
    await fetchList()
  } catch {
    // request.ts 已统一提示（状态冲突 / 批次重复等）
  } finally {
    receiving.value = false
  }
}

onMounted(async () => {
  await loadDictionaries()
  await fetchList()
})
</script>

<template>
  <div class="page">
    <div class="page-head glass-nav">
      <h2><span class="brand-name">念家鲜饺</span>采购管理</h2>
      <router-link to="/">← 返回首页</router-link>
    </div>

    <el-card shadow="never">
      <div class="toolbar">
        <span class="label">供应商</span>
        <el-select
          v-model="query.supplier_id"
          placeholder="全部供应商"
          clearable
          filterable
          style="width: 220px"
        >
          <el-option
            v-for="s in suppliers"
            :key="s.id"
            :label="s.name + '（' + s.supplier_no + '）'"
            :value="s.id"
          />
        </el-select>
        <el-select v-model="query.status" placeholder="全部状态" clearable style="width: 140px">
          <el-option v-for="it in PO_STATUS" :key="it.value" :label="it.label" :value="it.value" />
        </el-select>
        <el-button type="primary" @click="handleSearch">查询</el-button>
        <el-button @click="handleReset">重置</el-button>
        <el-button type="primary" plain @click="openCreate">新建采购单</el-button>
      </div>
      <p class="tip">
        采购收货后由后端在同一事务内生成批次库存并写入批次流水（receive_add），批次号即后续分拣 / 配送 / 报损的追溯入口。
      </p>

      <el-table v-loading="loading" :data="list" border stripe>
        <el-table-column prop="po_no" label="采购单号" width="180" />
        <el-table-column label="供应商" min-width="180">
          <template #default="{ row }">
            {{ supplierText(row.supplier_id, row.supplier_name) }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="poStatusTag(row.status)" effect="light">
              {{ poStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="预计到货" width="130">
          <template #default="{ row }">{{ formatDate(row.expected_date) }}</template>
        </el-table-column>
        <el-table-column label="金额" width="150" align="right">
          <template #default="{ row }">{{ formatMoney(row.total_amount) }}</template>
        </el-table-column>
        <el-table-column label="明细行数" width="110" align="center">
          <template #default="{ row }">
            {{ row.items && row.items.length > 0 ? row.items.length : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button link type="primary" @click="openDetail(asPurchaseOrder(row))">
                查看明细
              </el-button>
              <el-button
                v-if="row.status === 'draft' || row.status === 'submitted'"
                link
                type="primary"
                @click="openReceive(asPurchaseOrder(row))"
              >
                收货
              </el-button>
              <span v-else class="muted">—</span>
            </div>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :image-size="80" description="暂无采购单：点上方「新建采购单」向供应商下单" />
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

    <!-- 查看明细：列表随行返回 items，无需详情端点 -->
    <el-dialog v-model="detailVisible" title="采购单明细" width="900px" destroy-on-close>
      <template v-if="detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="采购单号">{{ detail.po_no }}</el-descriptions-item>
          <el-descriptions-item label="供应商">
            {{ supplierText(detail.supplier_id, detail.supplier_name) }}
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="poStatusTag(detail.status)" effect="light" size="small">
              {{ poStatusText(detail.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="预计到货">
            {{ formatDate(detail.expected_date) }}
          </el-descriptions-item>
          <el-descriptions-item label="总金额">
            {{ formatMoney(detail.total_amount) }}
          </el-descriptions-item>
          <el-descriptions-item label="备注">{{ detail.remark || '—' }}</el-descriptions-item>
        </el-descriptions>

        <el-table :data="detailItems" border stripe size="small" class="detail-table">
          <el-table-column label="SKU" min-width="200">
            <template #default="{ row }">
              {{ skuText(row.sku_id, row.sku_no, row.sku_name) }}
            </template>
          </el-table-column>
          <el-table-column label="订货数量" width="110" align="right">
            <template #default="{ row }">{{ formatQty(row.qty_unit) }}</template>
          </el-table-column>
          <el-table-column label="订货单位" width="100" align="center">
            <!-- el-table 插槽 row 为 DefaultRow，显式收窄后再传给具体类型函数 -->
            <template #default="{ row }">{{ unitText(row as PurchaseOrderItem) }}</template>
          </el-table-column>
          <el-table-column label="基础数量(基础单位)" width="160" align="right">
            <template #default="{ row }">{{ formatQty(row.qty_base) }}</template>
          </el-table-column>
          <el-table-column label="单价" width="120" align="right">
            <template #default="{ row }">{{ formatMoney(row.unit_price) }}</template>
          </el-table-column>
          <el-table-column label="金额" width="130" align="right">
            <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
          </el-table-column>
          <template #empty>
            <el-empty :image-size="60" description="该采购单暂无明细" />
          </template>
        </el-table>
      </template>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 新建采购单：POST /purchase-orders（幂等） -->
    <el-dialog v-model="createVisible" title="新建采购单" width="940px" destroy-on-close>
      <el-form ref="createFormRef" :model="createForm" :rules="createRules" label-width="110px">
        <el-form-item label="供应商" prop="supplier_id">
          <el-select v-model="createForm.supplier_id" filterable placeholder="选择供应商" style="width: 320px">
            <el-option
              v-for="s in suppliers"
              :key="s.id"
              :label="s.name + '（' + s.supplier_no + '）'"
              :value="s.id"
            />
          </el-select>
          <span v-if="suppliers.length === 0" class="hint">供应商列表未加载，请确认后端 /suppliers 可用</span>
        </el-form-item>
        <el-form-item label="预计到货日" prop="expected_date">
          <el-date-picker
            v-model="createForm.expected_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="可留空"
            clearable
            style="width: 200px"
          />
        </el-form-item>
        <el-form-item label="备注" prop="remark">
          <el-input
            v-model="createForm.remark"
            type="textarea"
            :rows="2"
            maxlength="255"
            show-word-limit
            placeholder="如：指定产地 / 送货时段"
          />
        </el-form-item>
      </el-form>

      <div class="sub-head">
        <span class="sub-title">采购明细</span>
        <span class="muted">SKU 单选 + 订货数量（订货单位）；单价留空 = 收货时取价目表现行价</span>
        <el-button type="primary" plain size="small" @click="addItemRow">添加一行</el-button>
      </div>

      <el-table :data="createForm.items" border stripe size="small" empty-text="还没有明细行，点「添加一行」">
        <el-table-column label="SKU" min-width="260">
          <template #default="{ row }">
            <el-select v-model="row.sku_id" filterable placeholder="选择 SKU" style="width: 100%">
              <el-option v-for="s in skus" :key="s.id" :label="s.sku_no + ' ' + s.name" :value="s.id" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="订货数量" width="160">
          <template #default="{ row }">
            <el-input-number v-model="row.qty_unit" :min="0" :precision="3" :step="1" style="width: 100%" />
          </template>
        </el-table-column>
        <el-table-column label="订货单位" width="100" align="center">
          <template #default="{ row }">{{ skuUnit(row.sku_id) }}</template>
        </el-table-column>
        <el-table-column label="单价(元)" width="180">
          <template #default="{ row }">
            <el-input-number
              v-model="row.unit_price"
              :min="0"
              :precision="4"
              :step="0.1"
              :controls="false"
              placeholder="留空取价目表"
              style="width: 100%"
            />
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
        <el-button type="primary" :loading="creating" @click="submitCreate">创建采购单</el-button>
      </template>
    </el-dialog>

    <!-- 收货入库：POST /purchase-orders/{id}/receive -->
    <el-dialog v-model="receiveVisible" title="收货入库" width="860px" destroy-on-close>
      <el-descriptions v-if="receiveTarget" :column="2" border size="small" class="receive-head">
        <el-descriptions-item label="采购单号">{{ receiveTarget.po_no }}</el-descriptions-item>
        <el-descriptions-item label="供应商">
          {{ supplierText(receiveTarget.supplier_id, receiveTarget.supplier_name) }}
        </el-descriptions-item>
        <el-descriptions-item label="预计到货">
          {{ formatDate(receiveTarget.expected_date) }}
        </el-descriptions-item>
        <el-descriptions-item label="总金额">
          {{ formatMoney(receiveTarget.total_amount) }}
        </el-descriptions-item>
      </el-descriptions>

      <el-form label-width="110px" class="receive-form">
        <el-form-item label="批次前缀">
          <el-input
            v-model="receiveForm.batch_no_prefix"
            maxlength="30"
            placeholder="如 B20261014（可留空 = 后端生成）"
            style="width: 300px"
          />
        </el-form-item>
        <el-form-item label="保质期至">
          <el-date-picker
            v-model="receiveForm.expire_at"
            type="datetime"
            value-format="YYYY-MM-DD HH:mm:ss"
            placeholder="选择保质期至（必填）"
            style="width: 300px"
          />
        </el-form-item>
      </el-form>

      <el-alert
        v-if="receiveForm.rows.length === 0"
        type="info"
        :closable="false"
        show-icon
        title="该采购单未返回明细，提交将按后端明细全量收货（不传 items）"
        class="block-gap"
      />

      <el-table v-else :data="receiveForm.rows" border stripe size="small">
        <el-table-column label="SKU" min-width="220">
          <template #default="{ row }">
            {{ skuText(row.sku_id, row.sku_no, row.sku_name) }}
          </template>
        </el-table-column>
        <el-table-column label="订货数量" width="140" align="right">
          <template #default="{ row }">{{ formatQty(row.qty_unit) }} {{ row.unit }}</template>
        </el-table-column>
        <el-table-column label="本次收货(基础单位)" width="200">
          <template #default="{ row }">
            <el-input-number v-model="row.qty_base" :min="0" :precision="3" :step="1" style="width: 100%" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" align="center">
          <template #default="{ $index }">
            <el-button link type="primary" @click="resetReceiveRow($index)">全量</el-button>
          </template>
        </el-table-column>
      </el-table>
      <p class="tip">
        提交后提示「已入库并写入批次流水」；数量为 0 的行不入库，至少一行需大于 0。
      </p>

      <template #footer>
        <el-button @click="receiveVisible = false">取消</el-button>
        <el-button type="primary" :loading="receiving" @click="submitReceive">确认收货</el-button>
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
/* 表格卡片化：白卡片 + 16px 圆角 + 柔和阴影 */
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
/* 行内操作：查看明细 / 收货并排，间距收紧 */
.row-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.sub-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 6px 0 10px;
}
.sub-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--nf-ink);
}
.detail-table {
  margin-top: 14px;
}
.receive-head {
  margin-bottom: 16px;
}
.receive-form {
  margin-bottom: 4px;
}
.block-gap {
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
.hint {
  margin-left: 8px;
}
@media (max-width: 900px) {
  .page {
    padding: 16px;
  }
}
</style>
