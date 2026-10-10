<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { apiLogin } from '../api'
import { setAuth } from '../composables/auth'

const router = useRouter()
const loading = ref(false)

const form = reactive({ username: '', password: '' })

async function doLogin() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    const json = await apiLogin(form.username, form.password)
    setAuth(json.data.token, json.data.username, json.data.isAdmin)
    ElMessage.success('登录成功')
    router.push('/')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <el-card class="login-card">
      <div class="login-title">国内比价工具</div>
      <el-form @keyup.enter="doLogin">
        <el-form-item>
          <el-input v-model="form.username" placeholder="用户名" size="large" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" type="password" show-password placeholder="密码" size="large" />
        </el-form-item>
        <el-button type="primary" size="large" class="full" :loading="loading" @click="doLogin">
          登 录
        </el-button>
      </el-form>
      <div class="tip">账号由管理员创建；初始管理员 admin / admin123</div>
    </el-card>
  </div>
</template>

<style scoped>
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1a7f4b 0%, #0d4d2e 100%);
}
.login-card {
  width: 380px;
  padding: 8px 12px 4px;
}
.login-title {
  text-align: center;
  font-size: 20px;
  font-weight: bold;
  color: #1a7f4b;
  margin-bottom: 12px;
}
.full {
  width: 100%;
}
.tip {
  margin-top: 12px;
  text-align: center;
  color: #999;
  font-size: 12px;
}
</style>
