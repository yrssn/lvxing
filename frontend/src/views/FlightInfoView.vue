<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiParamList, apiParamCreate, apiParamUpdate, apiParamDelete } from '../api'

const list = ref([])
const loading = ref(false)
const keyword = ref('')
const dialogVisible = ref(false)
const saving = ref(false)

const emptyForm = () => ({
  id: null,
  name: '',
  dpt: '',
  arr: '',
  flightNo: '',
  cabin: '',
  carrier: '',
  enabled: true,
  remark: '',
})
const form = reactive(emptyForm())

async function load() {
  loading.value = true
  try {
    const json = await apiParamList(keyword.value)
    list.value = json.data
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, emptyForm())
  dialogVisible.value = true
}

function openEdit(row) {
  Object.assign(form, {
    id: row.id,
    name: row.name,
    dpt: row.dpt,
    arr: row.arr,
    flightNo: row.flightNo,
    cabin: row.cabin,
    carrier: row.carrier,
    enabled: row.enabled,
    remark: row.remark,
  })
  dialogVisible.value = true
}

async function save() {
  if (!form.dpt.trim() || !form.arr.trim()) {
    ElMessage.warning('出发、到达机场为必填项')
    return
  }
  saving.value = true
  try {
    if (form.id) {
      await apiParamUpdate(form.id, { ...form })
      ElMessage.success('已更新')
    } else {
      await apiParamCreate({ ...form })
      ElMessage.success('已创建')
    }
    dialogVisible.value = false
    load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

async function toggle(row) {
  try {
    await apiParamUpdate(row.id, { ...row, enabled: row.enabled })
  } catch (e) {
    row.enabled = !row.enabled
    ElMessage.error(e.message)
  }
}

async function remove(row) {
  await ElMessageBox.confirm(`删除参数「${row.name}」？关联的定时任务将自动解除引用`, '提示', { type: 'warning' })
  try {
    await apiParamDelete(row.id)
    ElMessage.success('已删除')
    load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <el-card shadow="never">
      <template #header>
        <div class="card-head">
          <div class="filters">
            <el-input
              v-model="keyword"
              placeholder="按名称/航线/航班号搜索"
              clearable
              style="width: 240px"
              @keyup.enter="load"
              @clear="load"
            />
            <el-button type="primary" @click="load">搜索</el-button>
          </div>
          <el-button type="primary" @click="openCreate">
            <el-icon><Plus /></el-icon>&nbsp;新建参数
          </el-button>
        </div>
      </template>

      <el-table :data="list" v-loading="loading" size="small" border stripe>
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column label="航线" width="110">
          <template #default="{ row }">
            <el-tag size="small">{{ row.dpt }}→{{ row.arr }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="flightNo" label="航班号" width="100" />
        <el-table-column prop="cabin" label="舱位" width="70" />
        <el-table-column prop="carrier" label="航司" width="70" />
        <el-table-column label="启用" width="80">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" @change="toggle(row)" />
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="120" show-overflow-tooltip />
        <el-table-column prop="createdAt" label="创建时间" width="150" />
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑参数' : '新建参数'" width="480px">
      <el-form label-width="90px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="默认按航线自动生成" />
        </el-form-item>
        <el-form-item label="出发机场" required>
          <el-input v-model="form.dpt" placeholder="机场三字码，如 LHW" maxlength="3" />
        </el-form-item>
        <el-form-item label="到达机场" required>
          <el-input v-model="form.arr" placeholder="机场三字码，如 HGH" maxlength="3" />
        </el-form-item>
        <el-form-item label="航班号">
          <el-input v-model="form.flightNo" placeholder="可空" />
        </el-form-item>
        <el-form-item label="舱位">
          <el-input v-model="form.cabin" placeholder="可空，如 Y" maxlength="1" />
        </el-form-item>
        <el-form-item label="航司二字码">
          <el-input v-model="form.carrier" placeholder="可空，如 MU" maxlength="2" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.filters {
  display: flex;
  gap: 10px;
}
</style>
