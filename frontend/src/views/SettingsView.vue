<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiGetCookie, apiSaveCookie, apiTestCookie } from '../api'

const cookie = ref('')
const updatedAt = ref('')
const saving = ref(false)
const testing = ref(false)
const testResult = ref(null)

async function load() {
  try {
    const json = await apiGetCookie()
    cookie.value = json.data?.cookie || ''
    updatedAt.value = json.data?.updatedAt || ''
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function save() {
  saving.value = true
  try {
    await apiSaveCookie(cookie.value)
    ElMessage.success('Cookie 已保存')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

async function test() {
  testing.value = true
  testResult.value = null
  try {
    const json = await apiTestCookie()
    testResult.value = json.data
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    testing.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <el-card shadow="never">
      <template #header><span>网站 Cookie（手动抓取与定时任务共用）</span></template>
      <el-input
        v-model="cookie"
        type="textarea"
        :rows="6"
        placeholder="粘贴浏览器里目标站的完整 Cookie，例如：jt01=xxx; JSESSIONID=xxx"
      />
      <div class="hint">Cookie 保存在数据库中，供手动抓取和定时任务共同使用；失效后请重新从浏览器复制并保存。</div>
      <div class="actions">
        <el-button type="primary" :loading="saving" @click="save">保存 Cookie</el-button>
        <el-button :loading="testing" @click="test">测试 Cookie 是否有效</el-button>
        <span v-if="updatedAt" class="updated">上次更新：{{ updatedAt }}</span>
      </div>
      <el-alert
        v-if="testResult"
        :type="testResult.valid ? 'success' : 'error'"
        :title="testResult.message"
        :closable="false"
        class="mt"
      />
    </el-card>
  </div>
</template>

<style scoped>
.hint {
  margin-top: 10px;
  color: #999;
  font-size: 13px;
}
.actions {
  margin-top: 14px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.updated {
  color: #999;
  font-size: 13px;
}
.mt {
  margin-top: 12px;
}
</style>
