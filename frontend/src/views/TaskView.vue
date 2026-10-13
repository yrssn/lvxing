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
const emptyForm = () => ({
  id: null,
  name: '',
  paramIds: [],
  intervalDays: 1,
  timeOfDay: '08:00',
  daysAhead: 1,
  daysAheadTo: 0,
  minDelaySec: 3,
  maxDelaySec: 10,
  enabled: true,
})
const form = reactive(emptyForm())

function openCreate() {
  Object.assign(form, emptyForm())
  dialogVisible.value = true
}

function openEdit(row) {
  Object.assign(form, {
    id: row.id,
    name: row.name,
    paramIds: [...(row.paramIds || [])],
    intervalDays: row.intervalDays,
    timeOfDay: row.timeOfDay,
    daysAhead: row.daysAhead,
    daysAheadTo: row.daysAheadTo || 0,
    minDelaySec: row.minDelaySec,
    maxDelaySec: row.maxDelaySec,
    enabled: row.enabled,
  })
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
  if (form.daysAheadTo && form.daysAheadTo < form.daysAhead) {
    ElMessage.warning('抓取日期范围终点不能小于起点')
    return
  }
  saving.value = true
  try {
    if (form.id) {
      await apiTaskUpdate(form.id, { ...form })
      ElMessage.success('已更新，下次执行时间已重算')
    } else {
      await apiTaskCreate({ ...form })
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
        <el-table-column label="抓取日期" width="90">
          <template #default="{ row }">
            {{ row.daysAheadTo && row.daysAheadTo > row.daysAhead ? `${row.daysAhead}~${row.daysAheadTo}天后` : row.daysAhead === 0 ? '今天' : `${row.daysAhead}天后` }}
          </template>
        </el-table-column>
        <el-table-column label="频率" width="120">
          <template #default="{ row }">
            每 {{ row.intervalDays }} 天 {{ row.timeOfDay }}
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
    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑任务' : '新建任务'" width="560px">
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
        <el-form-item label="抓取航班日期">
          <div class="date-range">
            <span>提前</span>
            <el-input-number v-model="form.daysAhead" :min="0" :max="90" controls-position="right" style="width: 110px" />
            <span>至</span>
            <el-input-number v-model="form.daysAheadTo" :min="0" :max="90" controls-position="right" style="width: 110px" />
            <span>天后的航班日期（含当天；终点 0 = 只抓单日）</span>
          </div>
        </el-form-item>
        <el-form-item label="执行间隔">
          <el-input-number v-model="form.intervalDays" :min="1" :max="30" />
          <span class="tip-inline">天（1=每天，2=隔天）</span>
        </el-form-item>
        <el-form-item label="每日执行时刻">
          <el-time-select v-model="form.timeOfDay" start="00:00" step="00:05" end="23:55" />
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
