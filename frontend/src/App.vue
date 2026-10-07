<script setup>
import { computed, onMounted, reactive, ref } from 'vue'

/* ---------- Cookie 设置 ---------- */
const cookie = ref(localStorage.getItem('lvx_cookie') || '')
const showCookie = ref(!cookie.value)

function saveCookie() {
  localStorage.setItem('lvx_cookie', cookie.value.trim())
  showCookie.value = false
}

/* ---------- 查询历史 ---------- */
const historyList = ref([])
const viewingHistoryId = ref(null)

async function loadHistory() {
  try {
    const resp = await fetch('/api/history?limit=50')
    const json = await resp.json()
    if (json.success) historyList.value = json.data
  } catch {
    /* 数据库不可用时静默忽略 */
  }
}

async function viewHistory(item) {
  errorMsg.value = ''
  loading.value = true
  try {
    const resp = await fetch(`/api/history/${item.id}/records`)
    const json = await resp.json()
    if (json.success) {
      rows.value = json.data
      useDefinedCols.value = true
      viewingHistoryId.value = item.id
      rawText.value = ''
      if (!json.data.length) errorMsg.value = '该历史记录没有保存到结果行'
    } else {
      errorMsg.value = json.message || '读取历史失败'
    }
  } finally {
    loading.value = false
  }
}

async function removeHistory(item) {
  if (!confirm(`删除 ${item.dpt}→${item.arr} ${item.flightDate} 的历史记录？`)) return
  const resp = await fetch(`/api/history/${item.id}`, { method: 'DELETE' })
  const json = await resp.json()
  if (json.success) {
    if (viewingHistoryId.value === item.id) {
      rows.value = []
      viewingHistoryId.value = null
    }
    loadHistory()
  }
}

/* ---------- 查询表单 ---------- */
function tomorrow() {
  const d = new Date(Date.now() + 86400000)
  return d.toISOString().slice(0, 10)
}

const form = reactive({
  flightNo: '',
  dpt: 'LHW',
  arr: 'HGH',
  flightDate: tomorrow(),
  cabin: '',
  carrier: '',
})

/* ---------- 查询与结果 ---------- */
const loading = ref(false)
const errorMsg = ref('')
const rows = ref([])
const useDefinedCols = ref(false)
const rawText = ref('')

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

async function query() {
  if (!cookie.value.trim()) {
    showCookie.value = true
    errorMsg.value = '请先填写 Cookie'
    return
  }
  if (!form.dpt || !form.arr || !form.flightDate) {
    errorMsg.value = '出发、到达、航班日期为必填项'
    return
  }
  loading.value = true
  errorMsg.value = ''
  rows.value = []
  rawText.value = ''
  try {
    const qs = new URLSearchParams({
      cookie: cookie.value.trim(),
      flightNo: form.flightNo,
      dpt: form.dpt,
      arr: form.arr,
      flightDate: form.flightDate,
      cabin: form.cabin,
      carrier: form.carrier,
    })
    const resp = await fetch(`/api/bidding?${qs}`)
    const json = await resp.json()
    if (!resp.ok || !json.success) {
      errorMsg.value = json.message || `请求失败 (${resp.status})`
      return
    }
    const extracted = extractRows(json.raw)
    if (extracted) {
      rows.value = extracted
      useDefinedCols.value = 'orderList' in (json.raw?.data || {})
      viewingHistoryId.value = null
      loadHistory()
    } else {
      rawText.value = JSON.stringify(json.raw, null, 2)
    }
  } catch (e) {
    errorMsg.value = `请求异常: ${e.message}`
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

function fmt(col, row) {
  if (col.render) return col.render(row)
  const v = row[col.key]
  if (v === null || v === undefined) return ''
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

onMounted(() => {
  loadHistory()
  if (!cookie.value) {
    errorMsg.value = '首次使用请先在上方填写网站 Cookie 并保存'
  }
})
</script>

<template>
  <div class="page">
    <!-- 顶部栏 -->
    <header class="topbar">
      <span class="title">国内比价工具</span>
    </header>

    <!-- Cookie 设置 -->
    <section class="cookie-bar">
      <div class="cookie-head" @click="showCookie = !showCookie">
        <span>Cookie 设置</span>
        <span class="arrow">{{ showCookie ? '▲' : '▼' }}</span>
      </div>
      <div v-if="showCookie" class="cookie-body">
        <textarea
          v-model="cookie"
          rows="3"
          placeholder="粘贴浏览器里的完整 Cookie，例如：jt01=xxx; JSESSIONID=xxx"
        ></textarea>
        <button class="btn" @click="saveCookie">保存 Cookie</button>
        <span class="hint">Cookie 保存在本机浏览器中，仅用于本工具请求目标网站</span>
      </div>
    </section>

    <!-- 查询表单 -->
    <section class="query-box">
      <div class="form-grid">
        <div class="field">
          <label>航班号</label>
          <input v-model="form.flightNo" placeholder="可空" />
        </div>
        <div class="field">
          <label class="required">出发</label>
          <input v-model="form.dpt" placeholder="如 LHW" maxlength="3" />
        </div>
        <div class="field">
          <label class="required">到达</label>
          <input v-model="form.arr" placeholder="如 HGH" maxlength="3" />
        </div>
        <div class="field">
          <label class="required">航班日期</label>
          <input v-model="form.flightDate" type="date" />
        </div>
        <div class="field">
          <label>舱位</label>
          <input v-model="form.cabin" placeholder="可空，如 Y" maxlength="1" />
        </div>
        <div class="field">
          <label>航司二字码</label>
          <input v-model="form.carrier" placeholder="可空，如 MU" maxlength="2" />
        </div>
      </div>
      <div class="actions">
        <button class="btn primary" :disabled="loading" @click="query">
          {{ loading ? '查询中…' : '查看' }}
        </button>
      </div>
    </section>

    <!-- 错误提示 -->
    <div v-if="errorMsg" class="error">{{ errorMsg }}</div>

    <!-- 说明 -->
    <section class="notes">
      <p>注:</p>
      <p>1.*为必填项;</p>
    </section>

    <!-- 查询历史 -->
    <section v-if="historyList.length" class="history-wrap">
      <div class="history-head">
        <span>查询历史（已存 MySQL）</span>
        <button class="btn small" @click="loadHistory">刷新</button>
      </div>
      <div class="history-list">
        <div
          v-for="item in historyList"
          :key="item.id"
          class="history-item"
          :class="{ active: viewingHistoryId === item.id }"
        >
          <span class="hi-main clickable" @click="viewHistory(item)">
            {{ item.dpt }}→{{ item.arr }} · {{ item.flightDate }} · {{ item.rowCount }} 条
          </span>
          <span class="hi-sub">{{ item.createdAt }}</span>
          <button class="btn small danger" @click="removeHistory(item)">删除</button>
        </div>
      </div>
    </section>

    <!-- 结果表格 -->
    <section v-if="rows.length" class="table-wrap">
      <div v-if="viewingHistoryId" class="source-tip">
        正在查看历史记录 #{{ viewingHistoryId }}（来自 MySQL，非实时数据）
      </div>
      <table>
        <thead>
          <tr>
            <th v-for="col in columns" :key="col.key">{{ col.label }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, i) in rows" :key="i">
            <td v-for="col in columns" :key="col.key">{{ fmt(col, row) }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 未知结构时展示原始 JSON -->
    <section v-if="rawText" class="raw-box">
      <p class="raw-title">未识别到表格数据，原始返回：</p>
      <pre>{{ rawText }}</pre>
    </section>

    <section v-else-if="!rows.length && !loading && !errorMsg" class="empty">暂无数据，请输入条件后点击「查看」</section>
  </div>
</template>

<style scoped>
.page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 0 16px 40px;
}

.topbar {
  background: #1a7f4b;
  color: #fff;
  font-size: 18px;
  font-weight: bold;
  padding: 12px 20px;
  border-radius: 0 0 6px 6px;
}

.cookie-bar {
  background: #fff;
  border-radius: 6px;
  margin-top: 14px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  overflow: hidden;
}

.cookie-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  font-weight: bold;
  cursor: pointer;
  user-select: none;
}

.cookie-body {
  padding: 0 16px 14px;
}

.cookie-body textarea {
  width: 100%;
  padding: 8px;
  border: 1px solid #d9d9d9;
  border-radius: 4px;
  font-size: 13px;
  resize: vertical;
}

.cookie-body .hint {
  margin-left: 10px;
  color: #999;
  font-size: 12px;
}

.query-box {
  background: #fff;
  border: 2px solid #e64340;
  border-radius: 6px;
  margin-top: 14px;
  padding: 18px 16px 10px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 14px 20px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field label {
  color: #666;
}

.field label.required::after {
  content: ' *';
  color: #e64340;
}

.field input {
  height: 32px;
  padding: 0 8px;
  border: 1px solid #d9d9d9;
  border-radius: 4px;
  outline: none;
}

.field input:focus {
  border-color: #1a7f4b;
}

.actions {
  margin: 14px 0 8px;
  text-align: center;
}

.btn {
  height: 32px;
  padding: 0 22px;
  border: 1px solid #d9d9d9;
  border-radius: 4px;
  background: #fff;
  cursor: pointer;
}

.btn.primary {
  background: #1a7f4b;
  border-color: #1a7f4b;
  color: #fff;
  font-weight: bold;
}

.btn.primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error {
  margin-top: 12px;
  padding: 10px 14px;
  background: #fff2f0;
  border: 1px solid #ffccc7;
  border-radius: 4px;
  color: #e64340;
}

.notes {
  margin-top: 14px;
  color: #e64340;
  font-size: 13px;
  line-height: 1.8;
}

.history-wrap {
  margin-top: 14px;
  background: #fff;
  border-radius: 6px;
  padding: 12px 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.history-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: bold;
  margin-bottom: 10px;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 7px 10px;
  border: 1px solid #eee;
  border-radius: 4px;
  font-size: 13px;
}

.history-item.active {
  border-color: #1a7f4b;
  background: #f2faf5;
}

.hi-main {
  flex: 1;
}

.clickable {
  cursor: pointer;
  color: #1a7f4b;
}

.clickable:hover {
  text-decoration: underline;
}

.hi-sub {
  color: #999;
}

.btn.small {
  height: 26px;
  padding: 0 12px;
  font-size: 12px;
}

.btn.danger {
  color: #e64340;
  border-color: #f5b5b3;
}

.source-tip {
  padding: 8px 12px;
  background: #fffbe6;
  border-bottom: 1px solid #ffe58f;
  color: #ad8b00;
  font-size: 13px;
}

.table-wrap {
  margin-top: 12px;
  background: #fff;
  border-radius: 6px;
  overflow-x: auto;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

table {
  width: 100%;
  border-collapse: collapse;
  white-space: nowrap;
}

th,
td {
  border: 1px solid #e8e8e8;
  padding: 9px 12px;
  text-align: center;
}

thead th {
  background: #1a7f4b;
  color: #fff;
  font-weight: normal;
}

tbody tr:nth-child(even) {
  background: #f2faf5;
}

tbody tr:hover {
  background: #e3f4ea;
}

.raw-box {
  margin-top: 12px;
  background: #fff;
  border-radius: 6px;
  padding: 14px;
}

.raw-box pre {
  background: #f6f6f6;
  padding: 10px;
  border-radius: 4px;
  overflow-x: auto;
  font-size: 12px;
}

.raw-title {
  margin-bottom: 8px;
  color: #999;
}

.empty {
  margin-top: 24px;
  text-align: center;
  color: #999;
}
</style>
