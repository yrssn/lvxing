<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiTaskList, apiTaskCreate, apiTaskUpdate, apiTaskDelete, apiTaskToggle, apiTaskRunNow, apiTaskLogs, apiParamList } from '../api'

const list = ref([])
const params = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const saving = ref(false)

/* ---------- 列表 ---------- */
const statusTag = { success: 'success', partial: 'warning', failed: 'danger', running: 'info' }
const statusText = { success: '成功', partial: '部分成功', failed: '失败', running: '执行中' }

const paramsText = computed(() => {
  const map = {}
  for (const p of params.value) map[p.id] = `${p.dpt}→${p.arr}`
  return (ids) => (ids || []).map((id) => map[id] || `#${id}`).join('、')
})

async function load() {
  loading.value = true
  try {
    const [t, p] = await Promise.all([apiTaskList(), apiParamList()])
    list.value = t.data
    params.value = p.data
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

/* ---------- 新建 / 编辑 ---------- */
const WEEKDAY_OPTIONS = [
  { value: 0, label: '周一' },
  { value: 1, label: '周二' },
  { value: 2, label: '周三' },
  { value: 3, label: '周四' },
  { value: 4, label: '周五' },
  { value: 5, label: '周六' },
  { value: 6, label: '周日' },
]
const weekdayText = (s) =>
  (s || '').split(',').filter((x) => x !== '').map((x) => (WEEKDAY_OPTIONS[+x] || {}).label || x).join('、')

const emptyForm = () => ({
  id: null,
  name: '',
  paramIds: [],
  intervalDays: 1,
  timeOfDay: '08:00',
  weekdays: [],          // 每周执行日（多选），空=按间隔天数
  windowMode: 'rolling', // rolling=滚动窗口 fixed=固定日期段
  daysAhead: 1,
  daysAheadTo: 15,       // 默认抓未来 15 天，避免漏配只抓单日
  fixedDateRange: [],
  minDelaySec: 3,
  maxDelaySec: 10,
  enabled: true,
})
const form = reactive(emptyForm())

/* 执行频率三态：daily=每天 interval=每隔N天 weekly=每周指定 */
const freqMode = ref('daily')

function syncFreqMode() {
  if ((form.weekdays || []).length) freqMode.value = 'weekly'
  else if (form.intervalDays > 1) freqMode.value = 'interval'
  else freqMode.value = 'daily'
}

function onFreqModeChange(mode) {
  if (mode === 'daily') {
    form.intervalDays = 1
    form.weekdays = []
  } else if (mode === 'interval') {
    if (form.intervalDays <= 1) form.intervalDays = 2
    form.weekdays = []
  }
}

/* 抓取航班日期的天数（滚动窗口按偏移展开；固定段按日期差展开） */
const windowDays = computed(() => {
  if (form.windowMode === 'fixed') {
    const [a, b] = form.fixedDateRange || []
    if (!a || !b) return 0
    return Math.floor((new Date(b) - new Date(a)) / 86400000) + 1
  }
  const start = form.daysAhead || 0
  const end = form.daysAheadTo || start
  return Math.max(0, end - start + 1)
})

/* 执行量预估：航线数 × 天数；耗时按 平均延时+单次请求约3秒 估算 */
const estimate = computed(() => {
  const count = (form.paramIds || []).length * windowDays.value
  if (!count) return null
  const avgDelay = (Math.max(0, form.minDelaySec) + Math.max(0, form.maxDelaySec)) / 2
  const totalSec = Math.round(count * (avgDelay + 3))
  const mins = Math.max(1, Math.round(totalSec / 60))
  return { count, mins: totalSec >= 120 ? mins : null, totalSec }
})

function openCreate() {
  Object.assign(form, emptyForm())
  freqMode.value = 'daily'
  dialogVisible.value = true
}

function openEdit(row) {
  Object.assign(form, {
    id: row.id,
    name: row.name,
    paramIds: [...(row.paramIds || [])],
    intervalDays: row.intervalDays,
    timeOfDay: row.timeOfDay,
    weekdays: (row.weekdays || '').split(',').filter((x) => x !== '').map(Number),
    windowMode: row.windowMode || 'rolling',
    daysAhead: row.daysAhead,
    daysAheadTo: row.daysAheadTo || 0,
    fixedDateRange: row.fixedDateFrom ? [row.fixedDateFrom, row.fixedDateTo || row.fixedDateFrom] : [],
    minDelaySec: row.minDelaySec,
    maxDelaySec: row.maxDelaySec,
    enabled: row.enabled,
  })
  syncFreqMode()
  dialogVisible.value = true
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写任务名称')
    return
  }
  if (!form.paramIds.length) {
    ElMessage.warning('请选择至少一条航班信息参数')
    return
  }
  if (form.minDelaySec > form.maxDelaySec) {
    ElMessage.warning('最小延时不能大于最大延时')
    return
  }
  if (form.windowMode === 'rolling' && form.daysAheadTo && form.daysAheadTo < form.daysAhead) {
    ElMessage.warning('抓取日期范围终点不能小于起点')
    return
  }
  if (form.windowMode === 'fixed' && !(form.fixedDateRange || []).length) {
    ElMessage.warning('固定日期段模式请选择起止日期')
    return
  }
  if (freqMode.value === 'weekly' && !(form.weekdays || []).length) {
    ElMessage.warning('每周指定模式请至少勾选一个执行日')
    return
  }
  const payload = {
    ...form,
    intervalDays: freqMode.value === 'weekly' ? 1 : form.intervalDays,
    weekdays: freqMode.value === 'weekly' ? (form.weekdays || []).join(',') : '',
    fixedDateFrom: form.windowMode === 'fixed' ? form.fixedDateRange?.[0] || '' : '',
    fixedDateTo: form.windowMode === 'fixed' ? form.fixedDateRange?.[1] || '' : '',
  }
  saving.value = true
  try {
    if (form.id) {
      await apiTaskUpdate(form.id, payload)
      ElMessage.success('已更新，下次执行时间已重算')
    } else {
      await apiTaskCreate(payload)
      ElMessage.success('任务已创建')
    }
    dialogVisible.value = false
    load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

/* ---------- 启停 / 删除 / 立即执行 ---------- */
async function toggle(row) {
  try {
    await apiTaskToggle(row.id, row.enabled)
    ElMessage.success(row.enabled ? '已启用' : '已停用')
    load()
  } catch (e) {
    row.enabled = !row.enabled
    ElMessage.error(e.message)
  }
}

async function remove(row) {
  await ElMessageBox.confirm(`删除任务「${row.name}」？执行日志将一并删除`, '提示', { type: 'warning' })
  try {
    await apiTaskDelete(row.id)
    ElMessage.success('已删除')
    load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function runNow(row) {
  try {
    await apiTaskRunNow(row.id)
    ElMessage.success('已触发执行，可稍后查看日志')
    setTimeout(load, 3000)
  } catch (e) {
    ElMessage.error(e.message)
  }
}

/* ---------- 日志抽屉 ---------- */
const drawerVisible = ref(false)
const logs = ref([])
const logsLoading = ref(false)
const logsTaskName = ref('')

async function showLogs(row) {
  logsTaskName.value = row.name
  drawerVisible.value = true
  logsLoading.value = true
  try {
    const json = await apiTaskLogs(row.id)
    logs.value = json.data
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    logsLoading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <el-card shadow="never">
      <template #header>
        <div class="card-head">
          <span>定时任务（系统后台按设定时间自动抓取入库）</span>
          <el-button type="primary" @click="openCreate">
            <el-icon><Plus /></el-icon>&nbsp;新建任务
          </el-button>
        </div>
      </template>

      <el-table :data="list" v-loading="loading" size="small" border stripe>
        <el-table-column prop="id" label="#" width="50" />
        <el-table-column prop="name" label="任务名称" min-width="120" />
        <el-table-column label="抓取航线" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ paramsText(row.paramIds) || '-' }}</template>
        </el-table-column>
        <el-table-column label="抓取日期" width="130">
          <template #default="{ row }">
            <template v-if="row.windowMode === 'fixed'">
              {{ row.fixedDateFrom || '-' }}<template v-if="row.fixedDateTo && row.fixedDateTo !== row.fixedDateFrom"> ~ {{ row.fixedDateTo.slice(5) }}</template>
            </template>
            <template v-else>
              {{ row.daysAheadTo && row.daysAheadTo > row.daysAhead ? `${row.daysAhead}~${row.daysAheadTo}天后` : row.daysAhead === 0 ? '今天' : `${row.daysAhead}天后` }}
            </template>
          </template>
        </el-table-column>
        <el-table-column label="频率" width="150">
          <template #default="{ row }">
            <template v-if="row.weekdays">每周{{ weekdayText(row.weekdays) }}</template>
            <template v-else>每 {{ row.intervalDays }} 天</template>
            &nbsp;{{ row.timeOfDay }}
          </template>
        </el-table-column>
        <el-table-column label="延时(秒)" width="85">
          <template #default="{ row }">{{ row.minDelaySec }}~{{ row.maxDelaySec }}</template>
        </el-table-column>
        <el-table-column label="启用" width="70">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" @change="toggle(row)" />
          </template>
        </el-table-column>
        <el-table-column prop="nextRunAt" label="下次执行" width="150" />
        <el-table-column prop="lastRunAt" label="上次执行" width="150" />
        <el-table-column label="上次结果" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.lastStatus" size="small" :type="statusTag[row.lastStatus]">
              {{ statusText[row.lastStatus] }}
            </el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link type="success" :disabled="row.status === 'running'" @click="runNow(row)">
              立即执行
            </el-button>
            <el-button size="small" link type="primary" @click="showLogs(row)">日志</el-button>
            <el-button size="small" link type="primary" :disabled="row.status === 'running'" @click="openEdit(row)">
              编辑
            </el-button>
            <el-button size="small" link type="danger" :disabled="row.status === 'running'" @click="remove(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建/编辑任务 -->
    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑任务' : '新建任务'" width="640px">
      <el-form label-width="120px">
        <el-form-item label="任务名称" required>
          <el-input v-model="form.name" placeholder="如：LHW-HGH 每日抓取" />
        </el-form-item>
        <el-form-item label="航班信息参数" required>
          <el-select v-model="form.paramIds" multiple placeholder="选择要抓取的航线参数" style="width: 100%">
            <el-option
              v-for="p in params"
              :key="p.id"
              :label="`${p.name}（${p.dpt}→${p.arr}）${p.enabled ? '' : ' [已停用]'}`"
              :value="p.id"
            />
          </el-select>
          <div class="tip">抓取时按选择顺序逐条执行，参数可在「航班信息」模块维护</div>
        </el-form-item>
        <el-form-item label="抓取日期窗口" required>
          <el-radio-group v-model="form.windowMode">
            <el-radio-button value="rolling">滚动窗口</el-radio-button>
            <el-radio-button value="fixed">固定日期段</el-radio-button>
          </el-radio-group>
          <div class="tip" style="width: 100%">
            <template v-if="form.windowMode === 'rolling'">
              滚动窗口：每次执行时按「今天 + N 天」计算，窗口随日期滑动，适合每天持续采集价格快照
            </template>
            <template v-else>
              固定日期段：始终抓取所选的固定航班日期，适合集中监控某几个日期的价格
            </template>
          </div>
          <div v-if="form.windowMode === 'rolling'" class="date-range">
            <span>提前</span>
            <el-input-number v-model="form.daysAhead" :min="0" :max="90" controls-position="right" style="width: 110px" />
            <span>至</span>
            <el-input-number v-model="form.daysAheadTo" :min="0" :max="90" controls-position="right" style="width: 110px" />
            <span>天后的航班日期（含当天；终点 = 起点则只抓单日）</span>
          </div>
          <el-date-picker
            v-else
            v-model="form.fixedDateRange"
            type="daterange"
            range-separator="至"
            start-placeholder="起始航班日期"
            end-placeholder="结束航班日期"
            value-format="YYYY-MM-DD"
            :clearable="false"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="执行频率">
          <el-radio-group v-model="freqMode" @change="onFreqModeChange">
            <el-radio-button value="daily">每天</el-radio-button>
            <el-radio-button value="interval">每隔N天</el-radio-button>
            <el-radio-button value="weekly">每周指定</el-radio-button>
          </el-radio-group>
          <el-input-number
            v-if="freqMode === 'interval'"
            v-model="form.intervalDays"
            :min="2"
            :max="30"
            controls-position="right"
            style="margin-left: 12px"
          />
          <el-checkbox-group
            v-if="freqMode === 'weekly'"
            v-model="form.weekdays"
            style="margin-left: 12px"
          >
            <el-checkbox v-for="w in WEEKDAY_OPTIONS" :key="w.value" :value="w.value">{{ w.label }}</el-checkbox>
          </el-checkbox-group>
          <div class="tip" style="width: 100%">
            {{ freqMode === 'daily' ? '每天执行一次' : freqMode === 'interval' ? `每 ${form.intervalDays} 天执行一次` : '仅在勾选的星期几执行（可多选，如周一、周三、周五）' }}
          </div>
        </el-form-item>
        <el-form-item label="执行时刻">
          <el-time-select v-model="form.timeOfDay" start="00:00" step="00:05" end="23:55" />
        </el-form-item>
        <el-form-item v-if="estimate" label="本次执行量">
          <el-alert
            :title="`将发起 ${estimate.count} 次抓取（${form.paramIds.length} 条航线 × ${windowDays} 天）${estimate.mins ? `，预计耗时约 ${estimate.mins} 分钟` : `，预计耗时约 ${estimate.totalSec} 秒`}`"
            :type="estimate.count > 60 ? 'warning' : 'info'"
            :closable="false"
            show-icon
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="条目间随机延时">
          <el-input-number v-model="form.minDelaySec" :min="0" :max="3600" />
          <span class="tip-inline">~</span>
          <el-input-number v-model="form.maxDelaySec" :min="0" :max="3600" />
          <span class="tip-inline">秒（多条参数之间随机等待，避免抓取频繁）</span>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 执行日志 -->
    <el-drawer v-model="drawerVisible" :title="`执行日志 - ${logsTaskName}`" size="55%">
      <el-table :data="logs" v-loading="logsLoading" size="small" border>
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="detail-wrap">
              <el-table :data="row.detail" size="small" border>
                <el-table-column prop="name" label="参数" min-width="120" />
                <el-table-column label="航线" width="100">
                  <template #default="{ row: d }">{{ d.dpt }}→{{ d.arr }}</template>
                </el-table-column>
                <el-table-column prop="flightDate" label="航班日期" width="100" />
                <el-table-column prop="historyId" label="历史#" width="70" />
                <el-table-column prop="rowCount" label="行数" width="60" />
                <el-table-column prop="error" label="错误" min-width="140" />
              </el-table>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="id" label="#" width="55" />
        <el-table-column label="触发" width="75">
          <template #default="{ row }">
            <el-tag size="small" :type="row.trigger === 'manual' ? 'warning' : 'primary'">
              {{ row.trigger === 'manual' ? '手动' : '定时' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="startedAt" label="开始时间" width="150" />
        <el-table-column prop="finishedAt" label="结束时间" width="150" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTag[row.status] || 'info'">
              {{ statusText[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="成功/总数" width="90">
          <template #default="{ row }">{{ row.okParams }}/{{ row.totalParams }}</template>
        </el-table-column>
        <el-table-column prop="message" label="说明" min-width="160" show-overflow-tooltip />
      </el-table>
    </el-drawer>
  </div>
</template>

<style scoped>
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.tip {
  color: #999;
  font-size: 12px;
  line-height: 1.6;
}
.tip-inline {
  color: #999;
  font-size: 12px;
  margin: 0 8px;
}
.date-range {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.date-range span {
  color: #606266;
  font-size: 13px;
}
.detail-wrap {
  padding: 8px 12px;
}
</style>
