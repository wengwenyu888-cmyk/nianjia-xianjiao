<script setup lang="ts">
// SKU 列表：分页查询 + 类别筛选 + 新建（类别/规格/单位/换算系数/保质期/供应类型）
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'

import { createSku, getSkus, type Sku, type SkuPayload, type SupplyType } from '@/api/store'

/** 品类取值与 §7.1 sku.category 注释一致（馅料-肉馅/馅料-海鲜/面皮/调料/包材/鲜活） */
const categoryOptions = ['馅料-肉馅', '馅料-海鲜', '面皮', '调料', '包材', '鲜活']

/** 供应类型：direct 直配 / temp 临采 */
const supplyTypeOptions: { value: SupplyType; label: string }[] = [
  { value: 'direct', label: '直配' },
  { value: 'temp', label: '临采' }
]

/** 枚举值转显示文案 */
function supplyTypeText(v: SupplyType): string {
  return supplyTypeOptions.find((it) => it.value === v)?.label ?? v
}

// ---- 列表状态 ----
const loading = ref(false)
const list = ref<Sku[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const category = ref('')

// ---- 对话框状态 ----
const dialogVisible = ref(false)
const saving = ref(false)
const formRef = ref<FormInstance>()

/** 新建表单初值：换算系数 1、保质期 24 小时、供应类型直配 */
function emptyForm(): SkuPayload {
  return {
    sku_no: '',
    name: '',
    category: '',
    spec: '',
    unit: '',
    base_unit: '',
    convert_factor: 1,
    shelf_life_hours: 24,
    supply_type: 'direct',
    status: 1
  }
}

const form = reactive<SkuPayload>(emptyForm())

/** 表单校验：编码/品名/类别/单位/基础单位必填，换算系数与保质期为合法数值 */
const rules: FormRules = {
  sku_no: [{ required: true, message: '请输入 SKU 编码', trigger: 'blur' }],
  name: [{ required: true, message: '请输入品名', trigger: 'blur' }],
  category: [{ required: true, message: '请选择类别', trigger: 'change' }],
  unit: [{ required: true, message: '请输入订货/展示单位', trigger: 'blur' }],
  base_unit: [{ required: true, message: '请输入基础单位', trigger: 'blur' }],
  convert_factor: [
    { required: true, message: '请输入换算系数', trigger: 'change' },
    { type: 'number', min: 0.0001, message: '换算系数需大于 0', trigger: 'change' }
  ],
  shelf_life_hours: [
    { required: true, message: '请输入保质期（小时）', trigger: 'change' },
    { type: 'number', min: 1, message: '保质期需大于 0 小时', trigger: 'change' }
  ],
  supply_type: [{ required: true, message: '请选择供应类型', trigger: 'change' }]
}

/** 分页查询；后端未连通时 request.ts 已提示，这里仅置空列表保证页面可用 */
async function fetchList(): Promise<void> {
  loading.value = true
  try {
    const res = await getSkus({
      page: page.value,
      page_size: pageSize.value,
      category: category.value || undefined
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
  category.value = ''
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
    await createSku({ ...form })
    ElMessage.success('SKU 创建成功')
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
      <h2><span class="brand-name">念家鲜饺</span>SKU 管理</h2>
      <router-link to="/">← 返回首页</router-link>
    </div>

    <el-card shadow="never">
      <div class="toolbar">
        <el-select
          v-model="category"
          placeholder="按类别筛选"
          clearable
          style="width: 200px"
          @change="handleSearch"
        >
          <el-option v-for="it in categoryOptions" :key="it" :label="it" :value="it" />
        </el-select>
        <el-button @click="handleReset">重置</el-button>
        <el-button type="primary" plain @click="openCreate">新建 SKU</el-button>
      </div>

      <el-table v-loading="loading" :data="list" border stripe>
        <el-table-column prop="sku_no" label="SKU 编码" width="140" />
        <el-table-column prop="name" label="品名" min-width="140" />
        <el-table-column prop="category" label="类别" width="150" />
        <el-table-column prop="spec" label="规格" width="120" />
        <el-table-column label="单位换算" min-width="170">
          <template #default="{ row }">
            {{ row.unit }} = {{ row.convert_factor }} {{ row.base_unit }}
          </template>
        </el-table-column>
        <el-table-column label="保质期" width="100">
          <template #default="{ row }">{{ row.shelf_life_hours }} 小时</template>
        </el-table-column>
        <el-table-column label="供应类型" width="110">
          <template #default="{ row }">
            <el-tag :type="row.supply_type === 'direct' ? 'success' : 'warning'" effect="light">
              {{ supplyTypeText(row.supply_type) }}
            </el-tag>
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

    <el-dialog v-model="dialogVisible" title="新建 SKU" width="560px" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="120px">
        <el-form-item label="SKU 编码" prop="sku_no">
          <el-input v-model="form.sku_no" placeholder="如 SKU0001" maxlength="32" />
        </el-form-item>
        <el-form-item label="品名" prop="name">
          <el-input v-model="form.name" placeholder="如 猪肉白菜馅" maxlength="64" />
        </el-form-item>
        <el-form-item label="类别" prop="category">
          <el-select v-model="form.category" placeholder="请选择类别" style="width: 100%">
            <el-option v-for="it in categoryOptions" :key="it" :label="it" :value="it" />
          </el-select>
        </el-form-item>
        <el-form-item label="规格" prop="spec">
          <el-input v-model="form.spec" placeholder="如 5kg/袋" maxlength="64" />
        </el-form-item>
        <el-form-item label="订货单位" prop="unit">
          <el-input v-model="form.unit" placeholder="如 袋" maxlength="16" />
        </el-form-item>
        <el-form-item label="基础单位" prop="base_unit">
          <el-input v-model="form.base_unit" placeholder="如 kg" maxlength="16" />
        </el-form-item>
        <el-form-item label="换算系数" prop="convert_factor">
          <el-input-number
            v-model="form.convert_factor"
            :min="0.0001"
            :precision="4"
            :step="0.5"
            style="width: 100%"
          />
          <span class="hint">1 订货单位 = 多少基础单位</span>
        </el-form-item>
        <el-form-item label="保质期(小时)" prop="shelf_life_hours">
          <el-input-number
            v-model="form.shelf_life_hours"
            :min="1"
            :precision="0"
            :step="1"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="供应类型" prop="supply_type">
          <el-select v-model="form.supply_type" placeholder="请选择供应类型" style="width: 100%">
            <el-option
              v-for="it in supplyTypeOptions"
              :key="it.value"
              :label="it.label"
              :value="it.value"
            />
          </el-select>
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
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  padding: 12px 18px;
  border-radius: 12px;
  /* 顶栏深蓝渐变：品牌深蓝 ink → 主色（docs/07 色板 #0e346b → #157fd1） */
  background: linear-gradient(135deg, #0e346b 0%, #157fd1 100%);
  color: #ffffff;
}
.page-head h2 {
  margin: 0;
  font-size: 20px;
  color: #ffffff;
  letter-spacing: 1px;
}
/* 品牌字：与页面标题之间用半透明分隔线区分 */
.brand-name {
  font-weight: 700;
  letter-spacing: 3px;
  margin-right: 12px;
  padding-right: 12px;
  border-right: 1px solid rgba(255, 255, 255, 0.35);
}
/* 顶栏内的返回首页链接：浅蓝，hover 变白 */
.page-head a {
  color: #cfe3f7;
  text-decoration: none;
  font-size: 14px;
}
.page-head a:hover {
  color: #ffffff;
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
