<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiUserList, apiUserCreate, apiUserUpdate, apiUserDelete } from '../api'
import { getUsername } from '../composables/auth'

const list = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const saving = ref(false)
const current = reactive({ username: getUsername(), id: null })

const form = reactive({ username: '', password: '', isAdmin: false })

async function load() {
  loading.value = true
  try {
    const json = await apiUserList()
    list.value = json.data
    const me = list.value.find((u) => u.username === current.username)
    if (me) current.id = me.id
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.username = ''
  form.password = ''
  form.isAdmin = false
  dialogVisible.value = true
}

async function create() {
  if (!form.username.trim() || form.password.length < 6) {
    ElMessage.warning('用户名 3-32 位，密码至少 6 位')
    return
  }
  saving.value = true
  try {
    await apiUserCreate({ ...form })
    ElMessage.success('账号已创建')
    dialogVisible.value = false
    load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

async function resetPassword(row) {
  const { value } = await ElMessageBox.prompt(
    `为账号「${row.username}」设置新密码（至少 6 位）`,
    '重置密码',
    { inputType: 'password', inputPattern: /^.{6,}$/, inputErrorMessage: '密码至少 6 位' }
  )
  try {
    await apiUserUpdate(row.id, { password: value })
    ElMessage.success('密码已重置')
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function toggleActive(row) {
  try {
    await apiUserUpdate(row.id, { isActive: row.isActive })
    ElMessage.success(row.isActive ? '已启用' : '已停用')
  } catch (e) {
    row.isActive = !row.isActive
    ElMessage.error(e.message)
  }
}

async function remove(row) {
  await ElMessageBox.confirm(`删除账号「${row.username}」？`, '提示', { type: 'warning' })
  try {
    await apiUserDelete(row.id)
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
          <span>用户管理（仅管理员可见，账号由此创建）</span>
          <el-button type="primary" @click="openCreate">
            <el-icon><Plus /></el-icon>&nbsp;创建账号
          </el-button>
        </div>
      </template>

      <el-table :data="list" v-loading="loading" size="small" border stripe>
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column prop="username" label="用户名" min-width="140" />
        <el-table-column label="角色" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.isAdmin ? 'danger' : 'info'">
              {{ row.isAdmin ? '管理员' : '普通用户' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-switch
              v-model="row.isActive"
              :disabled="row.id === current.id"
              @change="toggleActive(row)"
            />
          </template>
        </el-table-column>
        <el-table-column prop="createdAt" label="创建时间" width="160" />
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="resetPassword(row)">重置密码</el-button>
            <el-button size="small" link type="danger" :disabled="row.id === current.id" @click="remove(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" title="创建账号" width="440px">
      <el-form label-width="90px">
        <el-form-item label="用户名" required>
          <el-input v-model="form.username" placeholder="3-32 位" maxlength="32" />
        </el-form-item>
        <el-form-item label="密码" required>
          <el-input v-model="form.password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="设为管理员">
          <el-switch v-model="form.isAdmin" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="create">创建</el-button>
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
</style>
