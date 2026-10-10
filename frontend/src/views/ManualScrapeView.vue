<script setup>
import { computed, onMounted, reactive, ref, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiScrapeRun, apiHistoryList, apiHistoryRecords, apiHistoryDelete, apiGetCookie } from '../api'
import { downloadCsv } from '../utils/csv'

const router = useRouter()

function tomorrow() {
  const d = new Date(Date.now() + 86400000)
  return d.toISOString().slice(0, 10)
}

/* ---------- 查询表单 ---------- */
const form = reactive({
  carrier: '',
  dpt: 'LHW',
  arr: 'HGH',
  flightNo: '',
  flightDate: tomorrow(),
  cabin: '',
})
const loading = ref(false)
const hasCookie = ref(true)

/* ---------- 结果与列 ---------- */
const rows = ref([])
const useDefinedCols = ref(false)
const viewingHistoryId = ref(null)

/* 与原站页面一致的列（字段名来自实际接口返回 data.orderList） */
const definedCols = [
  { key: 'flightDate', label: '日期' },
  { key: 'dpt', label: '出发机场' },
  { key: 'arr', label: '到达机场' },
  { key: 'flightNo', label: '航班号' },
  { key: 'mainFlightNo', label: '主飞航班号' },
  { key: 'cabin', label: '舱位' },
  { key: 'policyType', label: '政策类型' },
  { key: 'followBasePrice', label: '就旅伴外放退改价' },
  { key: 'sellPrice', label: '全网低价', render: (r) => (r.sellPrice ?? '') + (r.externalCabin ? `(${r.externalCabin})` : '') },
  { key: 'selfPrice', label: '自有政策', render: (r) => (r.selfPrice ? String(r.selfPrice) : '') },
]

const columns = computed(() => {
  if (useDefinedCols.value) return definedCols
  const keys = []
  const seen = new Set()
  for (const row of rows.value) {
    for (const k of Object.keys(row)) {
      if (!seen.has(k)) {
        seen.add(k)
        keys.push(k)
      }
    }
  }
  return keys.map((k) => ({ key: k, label: k }))
})

function fmt(col, row) {
  if (col.render) return col.render(row)
  const v = row[col.key]
  if (v === null || v === undefined) return ''
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

/* ---------- 日志输出区 ---------- */
const logs = ref([])
const logBox = ref(null)

function addLog(text) {
  const ts = new Date().toLocaleString('zh-CN', { hour12: false })
  logs.value.push(`[${ts}] ${text}`)
  if (logs.value.length > 200) logs.value = logs.value.slice(-200)
  nextTick(() => {
    if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight
  })
}

/* ---------- 查询 / 抓取入库 ---------- */
async function run(save) {
  if (!form.dpt || !form.arr || !form.flightDate) {
    ElMessage.warning('出发、到达、航班日期为必填项')
    return
  }
  loading.value = true
  const action = save ? '抓取并入库' : '查询'
  addLog(`${action}开始：${form.dpt}→${form.arr} ${form.flightDate}${form.flightNo ? ' 航班' + form.flightNo : ''}${form.carrier ? ' 航司' + form.carrier : ''}`)
  try {
    const json = await apiScrapeRun({ ...form, domain: 'shm', save })
    if (json.cookieInvalid) {
      addLog(`Cookie 已失效（目标站状态 ${json.status}），请到「系统设置」更新`)
      ElMessage.error('Cookie 已失效，请到系统设置更新')
      return
    }
    const extracted = extractRows(json.raw)
    if (extracted) {
      rows.value = extracted
      useDefinedCols.value = 'orderList' in (json.raw?.data || {})
      viewingHistoryId.value = null
      addLog(`${action}完成：返回 ${extracted.length} 行${json.historyId ? `，已入库（历史 #${json.historyId}）` : ''}`)
      if (save) loadHistory()
      else if (!json.historyId && extracted.length) addLog('提示：本次为查询查看，未入库')
    } else {
      rows.value = []
      addLog(`${action}完成：未识别到表格数据（状态 ${json.status}）`)
    }
  } catch (e) {
    addLog(`${action}失败：${e.message}`)
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

/* 从目标站返回的 JSON 中提取行数据，兼容常见包装结构 */
function extractRows(raw) {
  if (Array.isArray(raw)) return raw
  const candidates = [
    raw?.data,
    raw?.data?.orderList,
    raw?.data?.list,
    raw?.data?.rows,
    raw?.data?.records,
    raw?.rows,
    raw?.list,
    raw?.result,
  ]
  for (const c of candidates) {
    if (Array.isArray(c) && c.length > 0 && typeof c[0] === 'object') return c
  }
  return null
}

function refreshData() {
  run(false)
}

/* ---------- 导出当前表格 ---------- */
function exportRows() {
  if (!rows.value.length) {
    ElMessage.warning('当前没有可导出的数据')
    return
  }
  const headers = columns.value.map((c) => c.label)
  const data = rows.value.map((r) => columns.value.map((c) => fmt(c, r)))
  downloadCsv(`比价记录_${form.dpt}-${form.arr}_${form.flightDate}.csv`, headers, data)
  addLog(`导出记录：${rows.value.length} 行`)
}

/* ---------- 抓取历史（查看抓取的数据） ---------- */
const historyList = ref([])
const historyLoading = ref(false)

async function loadHistory() {
  try {
    const json = await apiHistoryList(50)
    if (json.success) historyList.value = json.data
  } catch {
    /* 数据库不可用时静默忽略 */
  }
}

async function viewHistory(item) {
  historyLoading.value = true
  try {
    const json = await apiHistoryRecords(item.id)
    if (json.success) {
      rows.value = json.data
      useDefinedCols.value = true
      viewingHistoryId.value = item.id
      addLog(`查看抓取数据：历史 #${item.id}（${item.dpt}→${item.arr} ${item.flightDate}），${json.data.length} 行`)
      if (!json.data.length) ElMessage.info('该历史记录没有保存到结果行')
    } else {
      ElMessage.error(json.message || '读取历史失败')
    }
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    historyLoading.value = false
  }
}

async function removeHistory(item) {
  await ElMessageBox.confirm(
    `删除 ${item.dpt}→${item.arr} ${item.flightDate} 的历史记录？`,
    '提示',
    { type: 'warning' }
  )
  try {
    const json = await apiHistoryDelete(item.id)
    if (json.success) {
      if (viewingHistoryId.value === item.id) {
        rows.value = []
        viewingHistoryId.value = null
      }
      addLog(`删除历史 #${item.id}，${json.deletedRows} 行`)
      loadHistory()
    }
  } catch (e) {
    ElMessage.error(e.message)
  }
}

onMounted(async () => {
  loadHistory()
  try {
    const json = await apiGetCookie()
    hasCookie.value = !!json.data?.cookie
    if (!hasCookie.value) {
      addLog('提示：尚未配置网站 Cookie，请先到「系统设置」填写')
    }
  } catch {
    /* ignore */
  }
})
</script>

<template>
  <div class="page">
    <el-alert
      v-if="!hasCookie"
      type="warning"
      :closable="false"
      class="cookie-alert"
      @click="router.push('/settings')"
    >
      <span class="link" @click="router.push('/settings')">尚未配置网站 Cookie，点击前往「系统设置」填写</span>
    </el-alert>

    <!-- 查询表单 -->
    <el-card shadow="never">
      <el-form inline class="query-form">
        <el-form-item label="航司">
          <el-input v-model="form.carrier" placeholder="航司二字码，可空" maxlength="2" style="width: 130px" />
        </el-form-item>
        <el-form-item label="起飞" required>
          <el-input v-model="form.dpt" placeholder="机场三字码" maxlength="3" style="width: 130px" />
        </el-form-item>
        <el-form-item label="到达" required>
          <el-input v-model="form.arr" placeholder="机场三字码" maxlength="3" style="width: 130px" />
        </el-form-item>
        <el-form-item label="航班号">
          <el-input v-model="form.flightNo" placeholder="可空" style="width: 130px" />
        </el-form-item>
        <el-form-item label="航班日期" required>
          <el-date-picker v-model="form.flightDate" type="date" value-format="YYYY-MM-DD" style="width: 150px" />
        </el-form-item>
        <el-form-item label="舱位">
          <el-input v-model="form.cabin" placeholder="可空，如 Y" maxlength="1" style="width: 100px" />
        </el-form-item>
      </el-form>
      <div class="actions">
        <el-button type="primary" :loading="loading" @click="run(false)">
          <el-icon><Search /></el-icon>&nbsp;查询
        </el-button>
        <el-button type="success" :loading="loading" @click="run(true)">
          <el-icon><Download /></el-icon>&nbsp;抓取并入库
        </el-button>
        <el-button type="warning" @click="exportRows">
          <el-icon><Document /></el-icon>&nbsp;导出记录
        </el-button>
        <el-button @click="refreshData">
          <el-icon><Refresh /></el-icon>&nbsp;刷新数据
        </el-button>
      </div>
    </el-card>

    <!-- 抓取历史 -->
    <el-card v-if="historyList.length" shadow="never" class="mt">
      <template #header>
        <div class="card-head">
          <span>抓取历史（已存数据库，点击查看抓取的数据）</span>
          <el-button size="small" @click="loadHistory">刷新</el-button>
        </div>
      </template>
      <el-table :data="historyList" size="small" v-loading="historyLoading" @row-click="viewHistory" class="click-table">
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column label="航线" width="120">
          <template #default="{ row }">{{ row.dpt }}→{{ row.arr }}</template>
        </el-table-column>
        <el-table-column prop="flightDate" label="航班日期" width="110" />
        <el-table-column prop="flightNo" label="航班号" width="100" />
        <el-table-column prop="rowCount" label="结果行数" width="90" />
        <el-table-column prop="createdAt" label="抓取时间" min-width="150" />
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button size="small" type="danger" link @click.stop="removeHistory(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 结果表格 -->
    <el-card v-if="rows.length" shadow="never" class="mt">
      <div v-if="viewingHistoryId" class="source-tip">
        正在查看历史记录 #{{ viewingHistoryId }}（来自数据库，非实时数据）
      </div>
      <el-table :data="rows" size="small" border stripe v-loading="loading">
        <el-table-column
          v-for="col in columns"
          :key="col.key"
          :label="col.label"
          :prop="col.render ? undefined : col.key"
          min-width="110"
        >
          <template #default="{ row }">{{ fmt(col, row) }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 日志输出区 -->
    <el-card shadow="never" class="mt">
      <template #header><span>报表日志输出区域</span></template>
      <div ref="logBox" class="log-box">
        <div v-if="!logs.length" class="log-empty">暂无日志</div>
        <div v-for="(l, i) in logs" :key="i" class="log-line">{{ l }}</div>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.cookie-alert {
  margin-bottom: 12px;
  cursor: pointer;
}
.link {
  color: #e6a23c;
}
.query-form :deep(.el-form-item) {
  margin-bottom: 8px;
}
.actions {
  display: flex;
  gap: 10px;
}
.mt {
  margin-top: 12px;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.click-table :deep(tbody tr) {
  cursor: pointer;
}
.source-tip {
  padding: 6px 10px;
  margin-bottom: 8px;
  background: #fffbe6;
  border: 1px solid #ffe58f;
  border-radius: 4px;
  color: #ad8b00;
  font-size: 13px;
}
.log-box {
  background: #14161f;
  color: #b9c0d0;
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
  line-height: 1.8;
  padding: 10px 12px;
  border-radius: 4px;
  height: 220px;
  overflow: auto;
}
.log-empty {
  color: #555;
}
</style>
