<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiXiamenTasks, apiXiamenTaskCreate, apiXiamenTaskUpdate, apiXiamenTaskRun, apiXiamenTaskStop, apiXiamenTaskToggle, apiXiamenTaskDelete, apiXiamenTaskLogs } from '../api'
const props = defineProps({ routes: { type: Array, default: () => [] } })
const emit = defineEmits(['refresh'])
const tasks = ref([]), loading = ref(false), saving = ref(false), dialog = ref(false)
const logs = ref([]), logTask = ref(null), drawer = ref(false)
const names = { idle: '空闲', queued: '排队中', running: '采集中', stopping: '正在停止', success: '完成', blocked: '已暂停', cancelled: '已停止', interrupted: '已中断', failed: '失败' }
const active = (t) => ['queued', 'running', 'stopping'].includes(t.status)
const fresh = () => ({ id: null, name: '', routeIds: [], windowMode: 'rolling', daysAhead: 1, daysCount: 7, fixedDateRange: [], intervalDays: 1, timeOfDay: '09:00', minDelaySec: 30, maxDelaySec: 60, mfOnly: true, enabled: false })
const form = reactive(fresh())
const days = computed(() => form.windowMode === 'rolling' ? form.daysCount : form.fixedDateRange?.length === 2 ? Math.round((new Date(form.fixedDateRange[1]) - new Date(form.fixedDateRange[0])) / 86400000) + 1 : 0)
const estimate = computed(() => {
  const n = form.routeIds.length * days.value
  return { count: n, minutes: Math.ceil((n * ((form.minDelaySec + form.maxDelaySec) / 2 + 5) + Math.floor(Math.max(0, n - 1) / 10) * 240) / 60) }
})
async function load(quiet = false) {
  if (!quiet) loading.value = true
  try { tasks.value = (await apiXiamenTasks()).data }
  catch (e) { if (!quiet) ElMessage.error(e.message) }
  finally { loading.value = false }
}
function edit(task) {
  Object.assign(form, fresh(), task || {}, { routeIds: [...(task?.routeIds || [])], fixedDateRange: task?.fixedDateFrom ? [task.fixedDateFrom, task.fixedDateTo || task.fixedDateFrom] : [] })
  dialog.value = true
}
async function save() {
  if (!form.name.trim() || !form.routeIds.length) return ElMessage.warning('请填写名称并选择航线')
  if (estimate.value.count < 1 || estimate.value.count > 200 || days.value > 30) return ElMessage.warning('请选择 1–30 天，航线数 × 天数不能超过 200')
  if (form.minDelaySec > form.maxDelaySec) return ElMessage.warning('最小间隔不能大于最大间隔')
  const payload = { ...form, fixedDateFrom: form.windowMode === 'fixed' ? form.fixedDateRange?.[0] : null, fixedDateTo: form.windowMode === 'fixed' ? form.fixedDateRange?.[1] : null }
  saving.value = true
  try {
    if (form.id) await apiXiamenTaskUpdate(form.id, payload)
    else await apiXiamenTaskCreate(payload)
    ElMessage.success(form.enabled ? '任务已保存，将按时间执行' : '任务已保存为停用状态，可先执行一次验证')
    dialog.value = false; await load()
  } catch (e) { ElMessage.error(e.message) }
  finally { saving.value = false }
}
async function action(task, kind) {
  try {
    if (kind === 'delete') {
      await ElMessageBox.confirm('删除此厦航任务？已经采集的报价和日志会保留。', '删除任务', { type: 'warning' })
      await apiXiamenTaskDelete(task.id)
    } else if (kind === 'run') {
      const result = await apiXiamenTaskRun(task.id); ElMessage.success(result.message)
    } else if (kind === 'stop') {
      const result = await apiXiamenTaskStop(task.id); ElMessage.success(result.message)
    } else await apiXiamenTaskToggle(task.id, !task.enabled)
    await load(); emit('refresh')
  } catch (e) { if (e !== 'cancel' && e !== 'close') ElMessage.error(e.message || '操作失败') }
}
async function showLogs(task) {
  logTask.value = task; drawer.value = true
  try { logs.value = (await apiXiamenTaskLogs(task.id)).data }
  catch (e) { ElMessage.error(e.message) }
}
let timer
onMounted(() => {
  load()
  timer = setInterval(async () => {
    if (document.hidden) return
    await load(true)
    if (drawer.value && logTask.value) {
      try { logs.value = (await apiXiamenTaskLogs(logTask.value.id)).data } catch { /* 下次刷新恢复 */ }
    }
  }, 5000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="toolbar"><div><strong>厦航采集任务</strong><p class="hint">独立调度和日志，只采集限时优惠。航线从已有列表选择，保存为出发/到达快照。</p></div><el-button type="primary" @click="edit()">新建厦航任务</el-button></div>
  <el-table :data="tasks" border v-loading="loading" empty-text="暂无厦航任务，建议先建一条航线、未来 3–7 天的小任务">
    <el-table-column prop="name" label="任务" min-width="140" />
    <el-table-column label="航线" min-width="160" show-overflow-tooltip><template #default="{ row }">{{ row.routes.map(r => `${r.dpt}→${r.arr}`).join('、') }}</template></el-table-column>
    <el-table-column label="航班日期" min-width="175"><template #default="{ row }">{{ row.windowMode === 'rolling' ? `从 ${row.daysAhead} 天后起，连续 ${row.daysCount} 天` : `${row.fixedDateFrom} 至 ${row.fixedDateTo}` }}</template></el-table-column>
    <el-table-column label="计划 / 间隔" width="145"><template #default="{ row }">每 {{ row.intervalDays }} 天 {{ row.timeOfDay }}<br><span class="hint">请求间隔 {{ row.minDelaySec }}–{{ row.maxDelaySec }} 秒</span></template></el-table-column>
    <el-table-column label="状态" width="105"><template #default="{ row }"><el-tag :type="active(row) ? 'warning' : row.enabled ? 'success' : 'info'">{{ active(row) ? names[row.status] : row.enabled ? '已启用' : '已停用' }}</el-tag><div class="hint">{{ names[row.lastStatus] || '' }}</div></template></el-table-column>
    <el-table-column label="下次执行" width="165"><template #default="{ row }">{{ row.nextRunAt?.replace('T', ' ') || '—' }}</template></el-table-column>
    <el-table-column label="操作" width="255" fixed="right"><template #default="{ row }">
      <el-button v-if="active(row)" link type="danger" :disabled="row.status === 'stopping'" @click="action(row, 'stop')">停止本次</el-button>
      <el-button v-else link type="success" @click="action(row, 'run')">执行一次</el-button>
      <el-button link type="primary" @click="showLogs(row)">进度 / 日志</el-button>
      <el-button link @click="action(row, 'toggle')">{{ row.enabled ? '停用' : '启用' }}</el-button>
      <el-button link :disabled="active(row)" @click="edit(row)">编辑</el-button>
      <el-button link type="danger" :disabled="active(row)" @click="action(row, 'delete')">删除</el-button>
    </template></el-table-column>
  </el-table>
  <el-dialog v-model="dialog" :title="form.id ? '编辑厦航任务' : '新建厦航任务'" width="720px">
    <el-form label-width="115px">
      <el-form-item label="任务名称"><el-input v-model="form.name" maxlength="100" placeholder="例如：上海至墨尔本限时优惠" /></el-form-item>
      <el-form-item label="航线"><el-select v-model="form.routeIds" multiple filterable style="width:100%" placeholder="从现有航线库选择"><el-option v-for="r in props.routes" :key="r.id" :value="r.id" :label="`${r.dpt} → ${r.arr}`" /></el-select><div class="hint">只使用机场三字码；不使用原航线的航班号、舱位或政策参数。需新增航线时前往“航班信息”。</div></el-form-item>
      <el-form-item label="航班日期"><el-radio-group v-model="form.windowMode"><el-radio-button value="rolling">未来 N 天</el-radio-button><el-radio-button value="fixed">固定日期段</el-radio-button></el-radio-group></el-form-item>
      <el-form-item v-if="form.windowMode === 'rolling'" label="日期范围"><div class="inline">从 <el-input-number v-model="form.daysAhead" :min="0" :max="90" style="width:110px" /> 天后起，连续 <el-input-number v-model="form.daysCount" :min="1" :max="30" style="width:110px" /> 天</div><div class="hint">例如从 1 天后起连续 7 天，就是明天至第 7 天；每次执行自动移动窗口。</div></el-form-item>
      <el-form-item v-else label="日期范围"><el-date-picker v-model="form.fixedDateRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" range-separator="至" /><div class="hint">最多 30 天，已过去的日期自动跳过，整个日期段结束后自动停用。</div></el-form-item>
      <el-form-item label="执行计划"><div class="inline">每 <el-input-number v-model="form.intervalDays" :min="1" :max="30" style="width:110px" /> 天 <el-time-select v-model="form.timeOfDay" start="00:00" end="23:55" step="00:05" style="width:130px" /> 执行（北京时间）</div></el-form-item>
      <el-form-item label="请求间隔"><div class="inline"><el-input-number v-model="form.minDelaySec" :min="30" :max="3600" style="width:130px" /> 至 <el-input-number v-model="form.maxDelaySec" :min="30" :max="3600" style="width:130px" /> 秒</div><div class="hint">首次也等待；每 10 次额外休息 3–5 分钟，所有厦航任务共用频率限制。</div></el-form-item>
      <el-form-item label="承运筛选"><el-checkbox v-model="form.mfOnly">仅保留每段均由厦航 MF 实际承运的优惠</el-checkbox></el-form-item>
      <el-form-item label="执行量"><el-alert :closable="false" :type="estimate.count > 200 ? 'error' : 'info'" :title="`${form.routeIds.length} 条航线 × ${days} 天 = 最多 ${estimate.count} 次请求；约 ${estimate.minutes} 分钟（不含排队或冷却）`" /><div class="hint">每次最多 200 次；所有厦航任务及手动查询每天合计最多 200 次。没有优惠的查询同样占用一次请求。</div></el-form-item>
      <el-form-item label="定时启用"><el-switch v-model="form.enabled" /><span class="hint" style="margin-left:12px">默认停用，可先“执行一次”验证后再启用定时。</span></el-form-item>
    </el-form>
    <template #footer><el-button @click="dialog=false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存任务</el-button></template>
  </el-dialog>
  <el-drawer v-model="drawer" :title="`${logTask?.name || ''} · 进度与日志`" size="75%">
    <p class="hint">每 5 秒自动刷新。停止后保留已完成数据；当前在途请求最多等待 45 秒。</p>
    <el-table :data="logs" border>
      <el-table-column type="expand"><template #default="{ row }"><el-table :data="row.detail" size="small"><el-table-column label="航线"><template #default="{ row: d }">{{ d.dpt }}→{{ d.arr }}</template></el-table-column><el-table-column prop="flightDate" label="日期" /><el-table-column prop="rowCount" label="优惠数" /><el-table-column label="来源"><template #default="{ row: d }">{{ d.cached ? '10 分钟缓存' : '查询' }}</template></el-table-column><el-table-column prop="error" label="停止原因" min-width="220" /></el-table></template></el-table-column>
      <el-table-column label="开始时间" width="165"><template #default="{ row }">{{ row.startedAt.replace('T',' ') }}</template></el-table-column>
      <el-table-column label="触发" width="70"><template #default="{ row }">{{ row.trigger === 'manual' ? '手动' : '定时' }}</template></el-table-column>
      <el-table-column label="状态" width="95"><template #default="{ row }">{{ names[row.status] || row.status }}</template></el-table-column>
      <el-table-column label="进度" width="90"><template #default="{ row }">{{ row.completed }}/{{ row.total }}</template></el-table-column>
      <el-table-column prop="offerCount" label="优惠数" width="80" />
      <el-table-column prop="message" label="当前进度 / 原因" min-width="220" />
    </el-table>
  </el-drawer>
</template>
<style scoped>.toolbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}.hint{font-size:12px;color:#606266;line-height:1.7;margin:6px 0 0;width:100%}.inline{display:flex;align-items:center;gap:8px;flex-wrap:wrap}</style>
