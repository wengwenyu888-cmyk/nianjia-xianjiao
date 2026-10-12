<script setup lang="ts">
// 门店列表：分页查询 + 关键字搜索 + 新建/编辑对话框（配送节奏枚举）
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'

import {
  createStore,
  getStores,
  updateStore,
  type DeliveryCycle,
  type Store,
  type StorePayload
} from '@/api/store'

/** 配送节奏选项，取值与 §7.1 store.delivery_cycle 一致 */
const deliveryCycleOptions: { value: DeliveryCycle; label: string }[] = [
  { value: 'daily', label: '日配' },
  { value: 'every_other_day', label: '隔日配' }
]

/** 枚举值转显示文案 */
function deliveryCycleText(v: DeliveryCycle): string {
  return deliveryCycleOptions.find((it) => it.value === v)?.label ?? v
}

// ---- 列表状态 ----
const loading = ref(false)
const list = ref<Store[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')

// ---- 对话框状态 ----
const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const editingId = ref<number | null>(null)
const saving = ref(false)
const formRef = ref<FormInstance>()

/** 新建表单初值（status=1 营业） */
function emptyForm(): StorePayload {
  return {
    store_no: '',
    name: '',
    region: '',
    address: '',
    contact_name: '',
    contact_phone: '',
    delivery_cycle: 'daily',
    status: 1
  }
}

const form = reactive<StorePayload>(emptyForm())

/** 表单校验：编码/名称/配送节奏必填 */
const rules: FormRules = {
  store_no: [{ required: true, message: '请输入门店编码', trigger: 'blur' }],
  name: [{ required: true, message: '请输入门店名称', trigger: 'blur' }],
  delivery_cycle: [{ required: true, message: '请选择配送节奏', trigger: 'change' }]
}

/** 分页查询；后端未连通时 request.ts 已提示，这里仅置空列表保证页面可用 */
async function fetchList(): Promise<void> {
  loading.value = true
  try {
    const res = await getStores({
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value.trim() || undefined
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
  keyword.value = ''
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
  dialogMode.value = 'create'
  editingId.value = null
  Object.assign(form, emptyForm())
  dialogVisible.value = true
}

function openEdit(row: Store): void {
  dialogMode.value = 'edit'
  editingId.value = row.id
  Object.assign(form, {
    ...emptyForm(),
    store_no: row.store_no,
    name: row.name,
    region: row.region ?? '',
    address: row.address ?? '',
    contact_name: row.contact_name ?? '',
    contact_phone: row.contact_phone ?? '',
    delivery_cycle: row.delivery_cycle,
    status: row.status
  })
  dialogVisible.value = true
}

async function submitForm(): Promise<void> {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    if (dialogMode.value === 'create') {
      await createStore({ ...form })
      ElMessage.success('门店创建成功')
    } else if (editingId.value !== null) {
      await updateStore(editingId.value, { ...form })
      ElMessage.success('门店已更新')
    }
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
      <h2><span class="brand-name">念家鲜饺</span>门店管理</h2>
      <router-link to="/">← 返回首页</router-link>
    </div>

    <el-card shadow="never">
      <div class="toolbar">
        <el-input
          v-model="keyword"
          placeholder="门店编码 / 名称"
          clearable
          style="width: 240px"
          @keyup.enter="handleSearch"
        />
        <el-button type="primary" @click="handleSearch">查询</el-button>
        <el-button @click="handleReset">重置</el-button>
        <el-button type="primary" plain @click="openCreate">新建门店</el-button>
      </div>

      <el-table v-loading="loading" :data="list" border stripe>
        <el-table-column prop="store_no" label="门店编码" width="140" />
        <el-table-column prop="name" label="门店名称" min-width="160" />
        <el-table-column prop="region" label="区域" width="120" />
        <el-table-column prop="contact_name" label="联系人" width="120" />
        <el-table-column prop="contact_phone" label="联系电话" width="140" />
        <el-table-column label="配送节奏" width="110">
          <template #default="{ row }">
            <el-tag :type="row.delivery_cycle === 'daily' ? 'success' : 'warning'" effect="light">
              {{ deliveryCycleText(row.delivery_cycle) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 1 ? 'success' : 'info'" effect="plain">
              {{ row.status === 1 ? '营业' : '停业' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
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

    <el-dialog
      v-model="dialogVisible"
      :title="dialogMode === 'create' ? '新建门店' : '编辑门店'"
      width="560px"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="96px">
        <el-form-item label="门店编码" prop="store_no">
          <el-input v-model="form.store_no" placeholder="如 S001" maxlength="32" />
        </el-form-item>
        <el-form-item label="门店名称" prop="name">
          <el-input v-model="form.name" placeholder="如 念家鲜饺·望京店" maxlength="64" />
        </el-form-item>
        <el-form-item label="区域" prop="region">
          <el-input v-model="form.region" placeholder="如 北京·朝阳" maxlength="64" />
        </el-form-item>
        <el-form-item label="地址" prop="address">
          <el-input v-model="form.address" placeholder="门店详细地址" maxlength="255" />
        </el-form-item>
        <el-form-item label="联系人" prop="contact_name">
          <el-input v-model="form.contact_name" maxlength="32" />
        </el-form-item>
        <el-form-item label="联系电话" prop="contact_phone">
          <el-input v-model="form.contact_phone" maxlength="32" />
        </el-form-item>
        <el-form-item label="配送节奏" prop="delivery_cycle">
          <el-select v-model="form.delivery_cycle" placeholder="请选择配送节奏" style="width: 100%">
            <el-option
              v-for="it in deliveryCycleOptions"
              :key="it.value"
              :label="it.label"
              :value="it.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="状态" prop="status">
          <el-switch
            v-model="form.status"
            :active-value="1"
            :inactive-value="0"
            active-text="营业"
            inactive-text="停业"
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
</style>
