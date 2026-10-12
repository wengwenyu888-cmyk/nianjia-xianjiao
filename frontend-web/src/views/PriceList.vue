<script setup lang="ts">
// 价目表：按 sku_id 与 date 过滤查询（§8.2 GET /prices）+ 新增价目（生效区间）
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'

import {
  createPrice,
  getPrices,
  type Price,
  type PricePayload,
  type PriceType
} from '@/api/store'

/** 价格类型：purchase 采购价 / transfer 内部调拨价 */
const priceTypeOptions: { value: PriceType; label: string }[] = [
  { value: 'purchase', label: '采购价' },
  { value: 'transfer', label: '调拨价' }
]

/** 枚举值转显示文案 */
function priceTypeText(v: PriceType): string {
  return priceTypeOptions.find((it) => it.value === v)?.label ?? v
}

// ---- 查询条件（sku_id + date 查历史当时价） ----
const query = reactive<{ sku_id: number | undefined; date: string }>({
  sku_id: undefined,
  date: ''
})

// ---- 列表状态 ----
const loading = ref(false)
const list = ref<Price[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

// ---- 对话框状态 ----
const dialogVisible = ref(false)
const saving = ref(false)
const formRef = ref<FormInstance>()

/** 新增价目表单初值：生效止留空表示现行有效 */
function emptyForm(): PricePayload {
  return {
    sku_id: 0,
    price_type: 'purchase',
    price: 0,
    effective_from: '',
    effective_to: null
  }
}

const form = reactive<PricePayload>(emptyForm())

/** 表单校验：SKU/类型/单价/生效起始必填，单价为正数 */
const rules: FormRules = {
  sku_id: [
    { required: true, message: '请输入 SKU ID', trigger: 'change' },
    { type: 'number', min: 1, message: 'SKU ID 需为正整数', trigger: 'change' }
  ],
  price_type: [{ required: true, message: '请选择价格类型', trigger: 'change' }],
  price: [
    { required: true, message: '请输入单价', trigger: 'change' },
    { type: 'number', min: 0.0001, message: '单价需大于 0', trigger: 'change' }
  ],
  effective_from: [{ required: true, message: '请选择生效起始日', trigger: 'change' }]
}

/** 分页查询；后端未连通时 request.ts 已提示，这里仅置空列表保证页面可用 */
async function fetchList(): Promise<void> {
  loading.value = true
  try {
    const res = await getPrices({
      page: page.value,
      page_size: pageSize.value,
      sku_id: query.sku_id,
      date: query.date || undefined
    })
    list.value = res?.list ?? []
    total.value = res?.total ?? 0
  } catch {
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
  query.sku_id = undefined
  query.date = ''
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

function openCreate(): void {
  Object.assign(form, emptyForm())
  dialogVisible.value = true
}

async function submitForm(): Promise<void> {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    await createPrice({ ...form, effective_to: form.effective_to || null })
    ElMessage.success('价目已新增')
    dialogVisible.value = false
    await fetchList()
  } catch {
    // request.ts 已统一弹出错误提示
  } finally {
    saving.value = false
  }
}

onMounted(fetchList)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2><span class="brand-name">念家鲜饺</span>价目表</h2>
      <router-link to="/">← 返回首页</router-link>
    </div>

    <el-card shadow="never">
      <div class="toolbar">
        <el-input-number
          v-model="query.sku_id"
          :min="1"
          :precision="0"
          placeholder="SKU ID"
          style="width: 150px"
        />
        <el-date-picker
          v-model="query.date"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="按日期查当时价"
          clearable
          style="width: 190px"
        />
        <el-button type="primary" @click="handleSearch">查询</el-button>
        <el-button @click="handleReset">重置</el-button>
        <el-button type="primary" plain @click="openCreate">新增价目</el-button>
      </div>

      <el-table v-loading="loading" :data="list" border stripe>
        <el-table-column prop="id" label="ID" width="90" />
        <el-table-column prop="sku_id" label="SKU ID" width="110" />
        <el-table-column label="价格类型" width="110">
          <template #default="{ row }">
            <el-tag :type="row.price_type === 'purchase' ? 'primary' : 'success'" effect="light">
              {{ priceTypeText(row.price_type) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="单价(元)" width="130">
          <template #default="{ row }">{{ row.price }}</template>
        </el-table-column>
        <el-table-column prop="effective_from" label="生效起始" width="130" />
        <el-table-column label="生效截止" min-width="130">
          <template #default="{ row }">
            <span v-if="row.effective_to">{{ row.effective_to }}</span>
            <el-tag v-else type="success" effect="plain">现行有效</el-tag>
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

    <el-dialog v-model="dialogVisible" title="新增价目" width="560px" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="120px">
        <el-form-item label="SKU ID" prop="sku_id">
          <el-input-number v-model="form.sku_id" :min="1" :precision="0" style="width: 100%" />
        </el-form-item>
        <el-form-item label="价格类型" prop="price_type">
          <el-select v-model="form.price_type" placeholder="请选择价格类型" style="width: 100%">
            <el-option
              v-for="it in priceTypeOptions"
              :key="it.value"
              :label="it.label"
              :value="it.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="单价(元)" prop="price">
          <el-input-number
            v-model="form.price"
            :min="0"
            :precision="4"
            :step="0.5"
            style="width: 100%"
          />
          <span class="hint">单价按订货单位计（§7.1 price.price）</span>
        </el-form-item>
        <el-form-item label="生效起始" prop="effective_from">
          <el-date-picker
            v-model="form.effective_from"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择生效起始日"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="生效截止" prop="effective_to">
          <el-date-picker
            v-model="form.effective_to"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="留空表示现行有效"
            clearable
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  padding: 24px;
}
/* 顶栏：毛玻璃白底（Apple 式克制），替代 V2 深蓝渐变 */
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
/* 页面标题：放大加粗（docs/07 §3 大字号层级 24px / 800） */
.page-head h2 {
  margin: 0;
  font-size: 24px;
  font-weight: 800;
  color: var(--nf-ink);
  letter-spacing: 0.5px;
}
/* 品牌字：深绿，右侧细分隔线与页面标题区分 */
.brand-name {
  font-weight: 800;
  letter-spacing: 3px;
  margin-right: 14px;
  padding-right: 14px;
  color: var(--nf-deep);
  border-right: 1px solid rgba(26, 26, 26, 0.1);
}
/* 顶栏内的返回首页链接：墨色辅助文字，hover 转品牌绿 */
.page-head a {
  color: #6b6b6b;
  text-decoration: none;
  font-size: 14px;
  transition: color 0.2s;
}
.page-head a:hover {
  color: var(--nf-green);
}
/* 表格卡片化：白色卡片 + 16px 圆角 + 柔和阴影，去掉默认描边
 * 直接写死 16px：Element 局部变量与懒加载 CSS 会覆盖 :root 变量，用字面值最稳。 */
.page :deep(.el-card) {
  border: none;
  border-radius: 16px;
  box-shadow: var(--nf-shadow-card);
  background: #ffffff;
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
.hint {
  margin-left: 8px;
  color: #909399;
  font-size: 12px;
}
</style>
