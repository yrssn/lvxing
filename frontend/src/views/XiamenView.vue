<script setup>
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiXiamenOffers, apiXiamenQuery, apiXiamenRoutes, apiXiamenSettings } from '../api'
import XiamenTasks from '../components/XiamenTasks.vue'
import XiamenSettings from '../components/XiamenSettings.vue'

const tab = ref('offers'), state = ref({}), routes = ref([])
const rows = ref([]), total = ref(0), loading = ref(false), querying = ref(false), queryMessage = ref('')
const queryOpen = ref(false), selectedRoute = ref(null)
function tomorrow() {
  const t = new Date(Date.now() + 86400000)
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(t)
}
const queryForm = reactive({ dpt: '', arr: '', flightDate: tomorrow(), mfOnly: true })
const filter = reactive({ dpt: '', arr: '', flightNo: '', latest: true, mfOnly: true, page: 1, pageSize: 20 })
const dates = ref([])
const duration = (n) => n == null ? '—' : `${Math.floor(n / 60)}小时${n % 60 ? `${n % 60}分` : ''}`
const clock = (v) => v?.aircraftScheduledDateTime?.replace('T', ' ') || '—'
async function refreshState() {
  try { state.value = (await apiXiamenSettings()).data } catch { /* 本地状态轮询不发送厦航请求 */ }
}
async function loadRoutes() {
  try { routes.value = (await apiXiamenRoutes()).data } catch (e) { ElMessage.error(e.message) }
}
async function load(reset = false) {
  if (reset) filter.page = 1
  loading.value = true
  try {
    const data = (await apiXiamenOffers({ ...filter, dateFrom: dates.value?.[0], dateTo: dates.value?.[1] })).data
    rows.value = data.items; total.value = data.total
  } catch (e) { ElMessage.error(e.message) }
  finally { loading.value = false }
}
function chooseRoute(id) {
  const r = routes.value.find(r => r.id === id)
  if (r) Object.assign(queryForm, { dpt: r.dpt, arr: r.arr })
}
async function query() {
  if (!queryForm.dpt || !queryForm.arr || !queryForm.flightDate) return ElMessage.warning('请选择航线和航班日期')
  querying.value = true; queryMessage.value = '正在按间隔等待并查询，请勿重复点击。结果将自动保存。'
  try {
    const result = (await apiXiamenQuery(queryForm)).data
    queryMessage.value = result.message
    ElMessage.success(result.message)
    queryOpen.value = false
    Object.assign(filter, { dpt: queryForm.dpt, arr: queryForm.arr, mfOnly: queryForm.mfOnly, page: 1 })
    dates.value = [queryForm.flightDate, queryForm.flightDate]
    await load()
  } catch (e) { queryMessage.value = e.message; ElMessage.error(e.message) }
  finally { querying.value = false; await refreshState() }
}
let timer
onMounted(() => {
  load(); loadRoutes(); refreshState()
  timer = setInterval(() => { if (!document.hidden) refreshState() }, 10000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="page xiamen-page">
    <el-card shadow="never" class="intro">
      <div class="heading"><div><h2>厦航限时优惠</h2><p>整程优惠 · 直飞与联程 · 独立采集</p></div><div class="quota"><strong>{{ state.todayCount || 0 }} <small>/ {{ state.dailyLimit || 200 }}</small></strong><span>今日请求 · 北京时间</span></div></div>
      <div class="status-line">
        <el-tag :type="state.configured && !state.blocked ? 'success' : 'warning'">{{ state.blocked ? '会话待更新' : state.configured ? '会话已配置' : '会话未配置' }}</el-tag>
        <el-tag v-if="state.cooldownUntil" type="danger">冷却至 {{ state.cooldownUntil.slice(0,19).replace('T',' ') }}</el-tag>
        <el-tag v-else-if="state.busy" type="warning">正在等待 / 采集</el-tag>
        <span>串行查询 · 默认间隔 30–60 秒 · 每 10 次休息 3–5 分钟</span>
      </div>
      <el-alert v-if="state.blocked || state.cooldownUntil" :title="state.reason" type="warning" :closable="false" show-icon style="margin-top:14px" />
    </el-card>

    <el-card shadow="never">
      <el-tabs v-model="tab">
        <el-tab-pane label="优惠数据" name="offers">
          <div class="toolbar"><p class="hint">以下为采集时的单成人含税报价，并非实时库存。默认只看各航线日期最近一次成功查询中的优惠。</p><el-button type="primary" :disabled="!state.configured || state.blocked || !!state.cooldownUntil || state.busy || querying" @click="queryOpen=true; loadRoutes()">单次查询</el-button></div>
          <div class="filters">
            <el-input v-model="filter.dpt" placeholder="查询出发三字码" maxlength="3" clearable style="width:150px" />
            <el-input v-model="filter.arr" placeholder="查询到达三字码" maxlength="3" clearable style="width:150px" />
            <el-input v-model="filter.flightNo" placeholder="航班号，如 MF803" clearable style="width:170px" />
            <el-date-picker v-model="dates" type="daterange" value-format="YYYY-MM-DD" start-placeholder="航班开始日期" end-placeholder="航班结束日期" style="width:270px" />
            <el-button @click="load(true)">筛选 / 刷新</el-button>
          </div>
          <div class="filters"><el-checkbox v-model="filter.latest" @change="load(true)">仅显示最新快照</el-checkbox><el-checkbox v-model="filter.mfOnly" @change="load(true)">仅厦航 MF 实际承运</el-checkbox><span class="hint">刷新只读取本地数据，不会请求厦航。</span></div>
          <el-table :data="rows" v-loading="loading" border stripe empty-text="暂无符合条件的限时优惠。可先单次查询，或在“采集任务”中设置航线及日期范围。">
            <el-table-column type="expand"><template #default="{ row }"><div class="expanded">
              <el-descriptions :column="3" border size="small"><el-descriptions-item label="票面价">{{ row.currency }} {{ row.baseAmount }}</el-descriptions-item><el-descriptions-item label="税费">{{ row.currency }} {{ row.taxAmount }}</el-descriptions-item><el-descriptions-item label="总行程时间">{{ duration(row.elapsedMinutes) }}</el-descriptions-item></el-descriptions>
              <div v-for="(segment, index) in row.segments" :key="index" class="segment">
                <strong>{{ segment.flightNo }} · 实际承运 {{ segment.operatingFlightNo || '未提供' }}</strong>
                <p>{{ segment.departure.iataLocationName }} {{ segment.departure.iataLocationCode }} {{ segment.departure.terminalName }} {{ clock(segment.departure) }} (UTC{{ segment.departure.timeZone?.designator }}) → {{ segment.arrival.iataLocationName }} {{ segment.arrival.iataLocationCode }} {{ segment.arrival.terminalName }} {{ clock(segment.arrival) }} (UTC{{ segment.arrival.timeZone?.designator }})</p>
                <el-tag v-if="row.transferMinutes[index] != null" type="info">中转停留 {{ duration(row.transferMinutes[index]) }}</el-tag>
              </div>
              <p><el-tag v-for="s in row.services" :key="s.type" style="margin:0 8px 6px 0" type="success">{{ s.name }}</el-tag></p>
              <p v-for="(p, i) in row.promotions" :key="i">{{ p.title }}：{{ p.description }}</p>
              <details><summary>行李说明（以航司条件及出票时为准）</summary><p class="baggage">{{ row.baggage || '未提供' }}</p></details>
              <p class="hint">查询路线 {{ row.requestedRoute.join(' → ') }} · {{ row.source === 'task' ? `任务 #${row.taskId}` : '单次查询' }} · 快照 #{{ row.queryId }}</p>
            </div></template></el-table-column>
            <el-table-column prop="flightDate" label="出发日期" width="110" />
            <el-table-column label="实际行程" min-width="170"><template #default="{ row }"><strong>{{ row.route.join(' → ') }}</strong><div class="hint">{{ row.segments.length > 1 ? '联程中转' : '单航段' }}</div></template></el-table-column>
            <el-table-column prop="flightNo" label="航班组合" min-width="180" />
            <el-table-column label="每段舱位" width="140"><template #default="{ row }">{{ row.cabinCodes.join(' / ') }}<div class="hint">{{ row.cabinTypes.map(c => ({ Economy:'经济', Business:'商务', First:'头等' }[c] || c)).join(' / ') }}</div></template></el-table-column>
            <el-table-column label="整程含税价" width="145" fixed="right"><template #default="{ row }"><strong class="price">{{ row.currency }} {{ row.totalAmount }}</strong></template></el-table-column>
            <el-table-column label="优惠" width="110"><template #default="{ row }"><el-tag type="warning">限时优惠</el-tag></template></el-table-column>
            <el-table-column label="实际承运" width="100"><template #default="{ row }">{{ row.allMf ? '全程厦航' : '含其他航司' }}</template></el-table-column>
            <el-table-column label="采集时间" width="165"><template #default="{ row }">{{ row.capturedAt.replace('T',' ') }}</template></el-table-column>
          </el-table>
          <el-pagination v-model:current-page="filter.page" :page-size="filter.pageSize" :total="total" layout="total, prev, pager, next" @current-change="load()" style="margin-top:18px" />
        </el-tab-pane>
        <el-tab-pane label="采集任务" name="tasks"><XiamenTasks v-if="tab === 'tasks'" :routes="routes" @refresh="refreshState" /><el-button link type="primary" @click="loadRoutes">刷新可用航线列表</el-button></el-tab-pane>
        <el-tab-pane label="连接设置" name="settings"><XiamenSettings :state="state" @saved="refreshState" /></el-tab-pane>
      </el-tabs>
    </el-card>

    <el-dialog v-model="queryOpen" title="单次查询厦航优惠" width="570px" :close-on-click-modal="!querying" :show-close="!querying" :close-on-press-escape="!querying">
      <el-alert title="只查询一条航线、一天；首次也等待 30–60 秒。批量日期请使用采集任务。" type="info" :closable="false" />
      <el-form label-width="95px" style="margin-top:20px">
        <el-form-item label="已有航线"><el-select v-model="selectedRoute" filterable placeholder="选择出发 → 到达" style="width:100%" :disabled="querying" @change="chooseRoute"><el-option v-for="r in routes" :key="r.id" :label="`${r.dpt} → ${r.arr}`" :value="r.id" /></el-select></el-form-item>
        <el-form-item label="航班日期"><el-date-picker v-model="queryForm.flightDate" type="date" value-format="YYYY-MM-DD" :disabled="querying" /></el-form-item>
        <el-form-item label="承运筛选"><el-checkbox v-model="queryForm.mfOnly" :disabled="querying">全程 MF 实际承运</el-checkbox></el-form-item>
      </el-form>
      <p class="hint">{{ queryMessage || '仅保存明确标注限时优惠的产品；查询无优惠时也记录成功快照。' }}</p>
      <template #footer><el-button :disabled="querying" @click="queryOpen=false">取消</el-button><el-button type="primary" :loading="querying" @click="query">查询并保存</el-button></template>
    </el-dialog>
  </div>
</template>
<style scoped>
.intro{margin-bottom:16px}.heading{display:flex;justify-content:space-between;align-items:center}.heading h2{margin:0;font-size:23px;color:#123b70}.heading p{color:#606266;margin:8px 0 14px}.quota{display:flex;flex-direction:column;text-align:right;gap:6px}.quota strong{font-size:28px;color:#123b70}.quota small{font-size:16px;color:#909399}.quota span,.hint{font-size:12px;color:#606266;line-height:1.7}.status-line{display:flex;align-items:center;gap:12px;flex-wrap:wrap;font-size:13px;color:#606266}.toolbar{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:12px}.filters{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:14px}.expanded{padding:20px;background:#f7faff}.segment{padding:14px 0;border-bottom:1px solid #e8edf3}.segment p{font-size:13px;line-height:1.8}.baggage{white-space:pre-wrap;line-height:1.8}.price{font-size:17px;color:#d37510}summary{cursor:pointer;color:#245b93}
.expanded{width:calc(100vw - 300px);max-width:100%;box-sizing:border-box}
</style>
