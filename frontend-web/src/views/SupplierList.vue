<script setup lang="ts">
// 供应商列表：分页查询 + 新建对话框（含账期 payment_terms 天）
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'

import {
  createSupplier,
  getSuppliers,
  type Supplier,
  type SupplierPayload
} from '@/api/store'

// ---- 列表状态 ----
const loading = ref(false)
const list = ref<Supplier[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

// ---- 对话框状态 ----
const dialogVisible = ref(false)
const saving = ref(false)
const formRef = ref<FormInstance>()

/** 新建表单初值：账期默认 0 天（现结） */
function emptyForm(): SupplierPayload {
  return {
    supplier_no: '',
    name: '',
    contact_name: '',
    contact_phone: '',
    payment_terms: 0,
    status: 1
  }
}

const form = reactive<SupplierPayload>(emptyForm())

/** 表单校验：编码/名称/账期必填，账期不可为负 */
const rules: FormRules = {
  supplier_no: [{ required: true, message: '请输入供应商编码', trigger: 'blur' }],
  name: [{ required: true, message: '请输入供应商名称', trigger: 'blur' }],
  payment_terms: [
    { required: true, message: '请输入账期（天）', trigger: 'change' },
    { type: 'number', min: 0, message: '账期不能为负数', trigger: 'change' }
  ]
}

/** 分页查询；后端未连通时 request.ts 已提示，这里仅置空列表保证页面可用 */
async function fetchList(): Promise<void> {
  loading.value = true
  try {
    const res = await getSuppliers({ page: page.value, page_size: pageSize.value })
    list.value = res?.list ?? []
    total.value = res?.total ?? 0
  } catch {
    list.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
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
    await createSupplier({ ...form })
    ElMessage.success('供应商创建成功')
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
      <h2><span class="brand-name">念家鲜饺</span>供应商管理</h2>
      <router-link to="/">← 返回首页</router-link>
    </div>

    <el-card shadow="never">
      <div class="toolbar">
        <el-button type="primary" plain @click="openCreate">新建供应商</el-button>
        <el-button @click="fetchList">刷新</el-button>
      </div>

      <el-table v-loading="loading" :data="list" border stripe>
        <el-table-column prop="supplier_no" label="供应商编码" width="150" />
        <el-table-column prop="name" label="供应商名称" min-width="180" />
        <el-table-column prop="contact_name" label="联系人" width="120" />
        <el-table-column prop="contact_phone" label="联系电话" width="140" />
        <el-table-column label="账期" width="110">
          <template #default="{ row }">
            <el-tag :type="row.payment_terms > 0 ? 'warning' : 'info'" effect="light">
              {{ row.payment_terms > 0 ? row.payment_terms + ' 天' : '现结' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 1 ? 'success' : 'info'" effect="plain">
              {{ row.status === 1 ? '启用' : '停用' }}
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

    <el-dialog v-model="dialogVisible" title="新建供应商" width="560px" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="110px">
        <el-form-item label="供应商编码" prop="supplier_no">
          <el-input v-model="form.supplier_no" placeholder="如 GYS001" maxlength="32" />
        </el-form-item>
        <el-form-item label="供应商名称" prop="name">
          <el-input v-model="form.name" placeholder="如 某某肉联厂" maxlength="64" />
        </el-form-item>
        <el-form-item label="联系人" prop="contact_name">
          <el-input v-model="form.contact_name" maxlength="32" />
        </el-form-item>
        <el-form-item label="联系电话" prop="contact_phone">
          <el-input v-model="form.contact_phone" maxlength="32" />
        </el-form-item>
        <el-form-item label="账期(天)" prop="payment_terms">
          <el-input-number
            v-model="form.payment_terms"
            :min="0"
            :precision="0"
            :step="1"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="状态" prop="status">
          <el-switch
            v-model="form.status"
            :active-value="1"
            :inactive-value="0"
            active-text="启用"
            inactive-text="停用"
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
