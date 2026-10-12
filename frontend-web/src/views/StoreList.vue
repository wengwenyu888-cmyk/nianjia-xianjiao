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
</style>
