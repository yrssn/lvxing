<script setup>
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiXiamenSaveSettings } from '../api'
import { isAdmin } from '../composables/auth'
defineProps({ state: { type: Object, default: () => ({}) } })
const emit = defineEmits(['saved'])
const form = reactive({ cookie: '', uds: '' })
const saving = ref(false)
async function save() {
  if (!form.cookie.trim() || !form.uds.trim()) return ElMessage.warning('请同时填写 Cookie 和 uds')
  saving.value = true
  try {
    await apiXiamenSaveSettings(form)
    form.cookie = ''; form.uds = ''
    ElMessage.success('厦航会话已更新，未发送查询请求')
    emit('saved')
  } catch (e) { ElMessage.error(e.message) }
  finally { saving.value = false }
}
</script>

<template>
  <div style="max-width: 900px">
    <el-alert :type="state.configured ? 'success' : 'warning'" :closable="false" show-icon
      :title="state.configured ? `已配置厦航会话 · 更新于 ${state.updatedAt?.replace('T', ' ')}` : '尚未配置厦航会话'" />
    <p class="hint">从厦航航班查询的同一条 shopping 请求中复制 Cookie 和 uds。两者独立于九旅行 Cookie；保存不会发送请求，也不会清除当天配额或冷却时间。保存后不回显凭据。</p>
    <el-form v-if="isAdmin()" label-position="top" @submit.prevent="save">
      <el-form-item label="厦航 Cookie"><el-input v-model="form.cookie" type="textarea" :rows="4" placeholder="粘贴完整 Cookie；更新时填写新值" /></el-form-item>
      <el-form-item label="uds 请求头"><el-input v-model="form.uds" type="password" show-password autocomplete="off" placeholder="粘贴同一请求的 uds 值" /></el-form-item>
      <el-button type="primary" :loading="saving" :disabled="state.busy" @click="save">保存厦航会话</el-button>
      <span v-if="state.busy" class="hint"> 请先停止任务，等待当前查询结束。</span>
    </el-form>
    <el-alert v-else title="请联系管理员更新厦航会话" type="info" :closable="false" />
    <el-divider />
    <h3>采集规则</h3>
    <ul class="rules">
      <li>单成人现金报价，只保存明确标注“限时优惠”的整程产品；不把舱位价差当优惠金额。</li>
      <li>首次查询也等待。默认每次间隔 30–60 秒，可在任务中延长；所有厦航任务和手动查询共用单一队列。</li>
      <li>每 10 次请求额外休息 3–5 分钟；每天最多 200 次请求，失败请求也计数，重启不重置。</li>
      <li>同航线、同日期、同承运筛选的成功结果在 10 分钟内复用，减少重复请求。</li>
      <li>限流或验证要求触发至少 1 小时冷却，并尊重服务器要求的更长等待；会话失效停止采集，更新后手动恢复任务。</li>
      <li>网络或接口错误停止当次任务，冷却 15 分钟；无自动连续重试。这些措施降低请求频率，不能保证不会触发风控。</li>
    </ul>
  </div>
</template>
<style scoped>.hint { color: #606266; line-height: 1.8; font-size: 13px; }.rules { color: #606266; line-height: 2; padding-left: 20px; }</style>
