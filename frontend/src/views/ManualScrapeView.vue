<script setup>
import { computed, onMounted, reactive, ref, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiScrapeRun, apiHistoryList, apiHistoryRecords, apiHistoryDelete, apiGetCookie, apiParamList } from '../api'
import { downloadCsv } from '../utils/csv'

const router = useRouter()

function tomorrow() {
  const d = new Date(Date.now() + 86400000)
  return fmtDate(d)
}

/* 本地时区安全的 YYYY-MM-DD（不用 toISOString，避免差一天） */
function fmtDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/* 把日期范围展开成逐天列表（最多 90 天） */
function eachDate(range) {
  const [a, b] = range || []
  if (!a || !b) return []
  const out = []
  const cur = new Date(`${a}T00:00:00`)
  const end = new Date(`${b}T00:00:00`)
  let guard = 0
  while (cur <= end && guard < 90) {
    out.push(fmtDate(cur))
    cur.setDate(cur.getDate() + 1)
    guard++
  }
  return out
}

/* ---------- 查询表单 ---------- */
const form = reactive({
  carrier: '',
  dpt: 'LHW',
  arr: 'HGH',
  flightNo: '',
  flightDateRange: [tomorrow(), tomorrow()],
  cabin: '',
})
const loading = ref(false)
const hasCookie = ref(true)

/* ---------- 结果与列 ---------- */
const rows = ref([])
/* 结果明细分页：新查询/切换历史时回到第 1 页 */
const rowsPage = ref(1)
const rowsPageSize = ref(10)
const pagedRows = computed(() => {
  const start = (rowsPage.value - 1) * rowsPageSize.value
  return rows.value.slice(start, start + rowsPageSize.value)
})
watch(rows, () => {
  rowsPage.value = 1
})
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

/* ---------- 航班信息快捷选择（预存查询参数） ---------- */
const paramOptions = ref([])
const selectedParams = ref([])
const PARAMS_STORAGE_KEY = 'manual_selected_params' /* 记住上次选中 */

async function loadParams() {
  try {
    const json = await apiParamList()
    if (json.success) {
      paramOptions.value = json.data.filter((p) => p.enabled)
      /* 恢复上次选中（仅保留仍存在且启用的选项） */
      try {
        const saved = JSON.parse(localStorage.getItem(PARAMS_STORAGE_KEY) || '[]')
        const valid = Array.isArray(saved) ? saved.filter((id) => paramOptions.value.some((p) => p.id === id)) : []
        if (valid.length) selectedParams.value = valid
      } catch { /* 忽略损坏的本地存储 */ }
    }
  } catch {
    /* 航班信息加载失败不阻塞页面 */
  }
}

function paramLabel(p) {
  const parts = [p.dpt, '→', p.arr]
  if (p.flightNo) parts.push(` ${p.flightNo}`)
  if (p.cabin) parts.push(` ${p.cabin}舱`)
  if (p.carrier) parts.push(` 航司${p.carrier}`)
  return parts.join('')
}

/* 单选时自动填充表单；多选走批量执行 */
watch(selectedParams, (ids) => {
  /* 持久化：下次进页面自动恢复 */
  localStorage.setItem(PARAMS_STORAGE_KEY, JSON.stringify(ids))
  if (ids.length === 1) {
    const p = paramOptions.value.find((x) => x.id === ids[0])
    if (p) {
      form.carrier = p.carrier || ''
      form.dpt = p.dpt || ''
      form.arr = p.arr || ''
      form.flightNo = p.flightNo || ''
      form.cabin = p.cabin || ''
      addLog(`已选择航班信息「${p.name}」：${paramLabel(p)}，点击「查询」或「抓取并入库」执行`)
    }
  }
})

/* ---------- 查询 / 抓取入库 ---------- */
async function run(save) {
  if (loading.value) return // 防重入：上一次请求未结束时忽略再次点击
  if (selectedParams.value.length > 1) {
    return runBatch(save)
  }
  if (!form.dpt || !form.arr) {
    ElMessage.warning('出发、到达为必填项')
    return
  }
  const dates = eachDate(form.flightDateRange)
  if (!dates.length) {
    ElMessage.warning('请选择航班日期范围')
    return
  }
  const base = {
    domain: 'shm',
    flightNo: form.flightNo,
    dpt: form.dpt,
    arr: form.arr,
    cabin: form.cabin,
    carrier: form.carrier,
  }
  /* 单日期：保持单次执行的完整结果展示；多日期：逐天执行 */
  if (dates.length === 1) {
    return runOnce(save, { ...base, flightDate: dates[0] })
  }
  const entries = dates.map((d) => ({
    label: `${form.dpt}→${form.arr} ${d}`,
    payload: { ...base, flightDate: d },
  }))
  return runSeries(save, entries)
}

/* 单次执行（单个航线 + 单个航班日期）：结果直接展示在表格 */
async function runOnce(save, payload) {
  loading.value = true
  const action = save ? '抓取并入库' : '查询'
  addLog(`${action}开始：${payload.dpt}→${payload.arr} ${payload.flightDate}${payload.flightNo ? ' 航班' + payload.flightNo : ''}${payload.carrier ? ' 航司' + payload.carrier : ''}`)
  try {
    const json = await apiScrapeRun(payload)
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
      addLog(`${action}完成：返回 ${extracted.length} 行${json.historyId ? `，已入库（历史 #${json.historyId}）` : ''}${json.duplicate ? '，10 秒内重复请求，未重复入库' : ''}`)
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

/* 批量执行器：entries = [{ label, payload }]，逐条请求、汇总日志；Cookie 失效立即终止 */
async function runSeries(save, entries) {
  loading.value = true
  const action = save ? '批量抓取并入库' : '批量查询'
  addLog(`${action}开始：共 ${entries.length} 次查询`)
  let ok = 0
  let fail = 0
  rows.value = []
  viewingHistoryId.value = null
  try {
    for (const { label, payload } of entries) {
      addLog(`  [${label}] 执行中…`)
      try {
        const json = await apiScrapeRun(payload)
        if (json.cookieInvalid) {
          addLog(`Cookie 已失效，批量任务提前终止（已完成 ${ok} 条，剩余 ${entries.length - ok - fail} 条未执行）`)
          ElMessage.error('Cookie 已失效，请到系统设置更新')
          fail++
          break
        }
        const extracted = extractRows(json.raw)
        if (extracted) {
          rows.value = rows.value.concat(extracted)
          useDefinedCols.value = 'orderList' in (json.raw?.data || {})
          addLog(`  [${label}] 完成：${extracted.length} 行${json.historyId ? `，已入库（历史 #${json.historyId}）` : ''}`)
          ok++
        } else {
          addLog(`  [${label}] 完成：未识别到表格数据（状态 ${json.status}）`)
          fail++
        }
      } catch (e) {
        addLog(`  [${label}] 失败：${e.message}`)
        fail++
      }
    }
    if (save && ok) loadHistory()
    addLog(`${action}结束：成功 ${ok} 次，失败 ${fail} 次${ok ? `，表格共 ${rows.value.length} 行` : ''}`)
  } finally {
    loading.value = false
  }
}

/* 多选航班信息：每条航线 × 航班日期范围内每一天，逐个执行 */
async function runBatch(save) {
  const dates = eachDate(form.flightDateRange)
  if (!dates.length) {
    ElMessage.warning('请先选择航班日期范围')
    return
  }
  const items = paramOptions.value.filter((p) => selectedParams.value.includes(p.id))
  if (!items.length) return
  const entries = []
  for (const p of items) {
    for (const d of dates) {
      entries.push({
        label: `${p.name} ${d}`,
        payload: {
          domain: p.domain || 'shm',
          flightNo: p.flightNo || '',
          dpt: p.dpt,
          arr: p.arr,
          flightDate: d,
          cabin: p.cabin || '',
          carrier: p.carrier || '',
          save,
        },
      })
    }
  }
  return runSeries(save, entries)
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
  downloadCsv(`比价记录_${form.dpt}-${form.arr}_${form.flightDateRange?.[0] || ''}至${form.flightDateRange?.[1] || ''}.csv`, headers, data)
  addLog(`导出记录：${rows.value.length} 行`)
}

/* ---------- 抓取历史（查看抓取的数据） ---------- */
const historyList = ref([])
const historyLoading = ref(false)
const historyPage = ref(1)
const historyPageSize = ref(10)
const pagedHistory = computed(() => {
  const start = (historyPage.value - 1) * historyPageSize.value
  return historyList.value.slice(start, start + historyPageSize.value)
})

async function loadHistory() {
  try {
    const json = await apiHistoryList(50)
    if (json.success) {
      historyList.value = json.data
      /* 删除后当前页可能超出范围，回退到最后一页 */
      const maxPage = Math.max(1, Math.ceil(historyList.value.length / historyPageSize.value))
      if (historyPage.value > maxPage) historyPage.value = maxPage
    }
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
  loadParams()
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
        <el-form-item label="航班信息">
          <el-select
            v-model="selectedParams"
            multiple
            filterable
            clearable
            placeholder="可多选：单选自动填充，多选批量执行"
            class="params-select"
          >
            <el-option
              v-for="p in paramOptions"
              :key="p.id"
              :label="`${p.name}（${paramLabel(p)}）`"
              :value="p.id"
            />
          </el-select>
        </el-form-item>
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
          <el-date-picker
            v-model="form.flightDateRange"
            type="daterange"
            range-separator="至"
            start-placeholder="开始"
            end-placeholder="结束"
            value-format="YYYY-MM-DD"
            :clearable="false"
            style="width: 260px"
          />
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
      <el-table :data="pagedHistory" size="small" v-loading="historyLoading" @row-click="viewHistory" class="click-table">
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
      <div class="pager">
        <el-pagination
          v-model:current-page="historyPage"
          v-model:page-size="historyPageSize"
          :total="historyList.length"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          background
          small
        />
      </div>
    </el-card>

    <!-- 结果表格 -->
    <el-card v-if="rows.length" shadow="never" class="mt">
      <div v-if="viewingHistoryId" class="source-tip">
        正在查看历史记录 #{{ viewingHistoryId }}（来自数据库，非实时数据）
      </div>
      <el-table :data="pagedRows" size="small" border stripe v-loading="loading">
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
      <div v-if="rows.length > rowsPageSize" class="pager">
        <el-pagination
          v-model:current-page="rowsPage"
          v-model:page-size="rowsPageSize"
          :total="rows.length"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          background
          small
        />
      </div>
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
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 10px;
}
/* 航班信息多选框：加宽，选中标签全部平铺展示、自动换行撑高 */
.params-select {
  width: 460px;
}
.params-select :deep(.el-select__selection) {
  flex-wrap: wrap;
  row-gap: 2px;
}
.params-select :deep(.el-select__wrapper) {
  min-height: 40px;
  height: auto;
  max-height: none;
  align-items: flex-start;
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
