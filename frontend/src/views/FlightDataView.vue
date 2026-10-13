<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiDataRecords, apiDataTrend, apiDataPolicyTypes, apiParamList } from '../api'
import { downloadCsv } from '../utils/csv'
import TrendChart from '../components/TrendChart.vue'

const loading = ref(false)
const list = ref([])
const total = ref(0)

/* ---------- 筛选 ---------- */
const filters = reactive({
  dpt: '',
  arr: '',
  flightNo: '',
  policyType: [],
  source: '',
  flightDateRange: null, // [from, to] 航班日期
  crawlRange: null, // [from, to] 抓取时间
})
const page = reactive({ current: 1, size: 20 })

function buildFilterParams() {
  const range = filters.flightDateRange || []
  const crawl = filters.crawlRange || []
  return {
    dpt: filters.dpt,
    arr: filters.arr,
    flightNo: filters.flightNo,
    policyType: filters.policyType,
    source: filters.source,
    flightDateFrom: range[0] || '',
    flightDateTo: range[1] || '',
    crawlFrom: crawl[0] || '',
    crawlTo: crawl[1] || '',
  }
}

async function load() {
  loading.value = true
  try {
    const json = await apiDataRecords({ ...buildFilterParams(), page: page.current, pageSize: page.size })
    list.value = json.data.items
    total.value = json.data.total
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

function search() {
  page.current = 1
  load()
}

function resetFilters() {
  filters.dpt = ''
  filters.arr = ''
  filters.flightNo = ''
  filters.policyType = []
  filters.source = ''
  filters.flightDateRange = null
  filters.crawlRange = null
  search()
}

/* ---------- 政策类型选项（来自数据库 distinct） ---------- */
const policyTypeOptions = ref([])

async function loadPolicyTypes() {
  try {
    const json = await apiDataPolicyTypes()
    if (json.success) policyTypeOptions.value = json.data
  } catch {
    /* ignore */
  }
}

/* ---------- 导出当前筛选全部数据 ---------- */
const exporting = ref(false)

const csvHeaders = [
  '数据更新时间', '来源', '航班日期', '起飞', '到达', '航班号', '主飞航班号',
  '舱位', '政策类型', '就旅伴外放退改价', '全网低价', '外放舱位', '自有政策',
]

function rowToCsv(r) {
  return [
    r.createdAt, r.source === 'manual' ? '手动' : '定时', r.flightDate, r.dpt, r.arr, r.flightNo, r.mainFlightNo,
    r.cabin, r.policyType, r.followBasePrice ?? '', r.sellPrice ?? '', r.externalCabin, r.selfPrice ?? '',
  ]
}

async function exportAll() {
  exporting.value = true
  try {
    const json = await apiDataRecords({ ...buildFilterParams(), page: 1, pageSize: 10000 })
    if (!json.data.items.length) {
      ElMessage.warning('当前筛选下没有数据')
      return
    }
    downloadCsv(`航班数据_${Date.now()}.csv`, csvHeaders, json.data.items.map(rowToCsv))
    ElMessage.success(`已导出 ${json.data.items.length} 行`)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    exporting.value = false
  }
}

/* ---------- 走势图 ---------- */
const trendVisible = ref(false)
const trendLoading = ref(false)
const trendData = ref([])

/* 走势弹窗内筛选：航班信息下拉 / 航班号 + 固定航班日期范围（每一天一个点） */
const paramList = ref([])
const trendParamId = ref(null)
const trendFlightNo = ref('')
const trendDateRange = ref(defaultTrendRange())
const trendPolicyTypes = ref([]) /* 弹窗内政策类型筛选：看指定产品的价格 */

function defaultTrendRange() {
  const fmt = (d) => d.toISOString().slice(0, 10)
  const start = new Date()
  const end = new Date(Date.now() + 14 * 86400000)
  return [fmt(start), fmt(end)]
}

async function loadParams() {
  try {
    const json = await apiParamList()
    if (json.success) paramList.value = json.data.filter((p) => p.enabled)
  } catch {
    /* ignore */
  }
}

function paramLabel(p) {
  const parts = [p.dpt, '→', p.arr]
  if (p.flightNo) parts.push(` ${p.flightNo}`)
  if (p.cabin) parts.push(` ${p.cabin}舱`)
  if (p.carrier) parts.push(` 航司${p.carrier}`)
  return parts.join('')
}

function trendBaseParams() {
  const base = buildFilterParams()
  const range = trendDateRange.value || []
  base.flightDateFrom = range[0] || ''
  base.flightDateTo = range[1] || ''
  base.policyType = trendPolicyTypes.value /* 弹窗内选择优先于列表筛选 */
  const p = paramList.value.find((x) => x.id === trendParamId.value)
  if (p) {
    base.dpt = p.dpt
    base.arr = p.arr
    base.flightNo = trendFlightNo.value.trim() || p.flightNo || ''
    base.carrier = p.carrier || ''
  } else {
    base.flightNo = trendFlightNo.value.trim()
  }
  return base
}

const trendRoute = computed(() => {
  const f = trendBaseParams()
  const parts = []
  parts.push(`${f.dpt || '*'}→${f.arr || '*'}`)
  if (f.flightNo) parts.push(`航班${f.flightNo}`)
  if (f.carrier) parts.push(`航司${f.carrier}`)
  if (trendPolicyTypes.value.length) parts.push(trendPolicyTypes.value.join('/'))
  const onlyDefault = !f.dpt && !f.arr && !f.flightNo && !f.carrier
  return onlyDefault && !trendPolicyTypes.value.length ? '全部航线' : parts.join(' · ')
})

/* 把日期范围内每一天补全为 X 轴（没抓取数据的天为空点，走势断开） */
function fillDateGaps(list, from, to) {
  if (!from || !to) return list
  const map = new Map(list.map((d) => [d.flightDate, d]))
  const out = []
  const cur = new Date(`${from}T00:00:00`)
  const end = new Date(`${to}T00:00:00`)
  let guard = 0
  while (cur <= end && guard < 400) {
    const key = cur.toISOString().slice(0, 10)
    out.push(
      map.get(key) || {
        flightDate: key,
        minSellPrice: null,
        minSelfPrice: null,
        sellCabin: '',
        selfCabin: '',
      }
    )
    cur.setDate(cur.getDate() + 1)
    guard++
  }
  return out
}

async function loadTrend() {
  trendLoading.value = true
  try {
    const params = trendBaseParams()
    const json = await apiDataTrend(params)
    trendData.value = fillDateGaps(json.data, params.flightDateFrom, params.flightDateTo)
    if (!json.data.length) ElMessage.info('当前筛选下没有可用于走势图的数据')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    trendLoading.value = false
  }
}

function showTrend() {
  /* 打开时继承列表当前的政策类型筛选，可在弹窗内再改 */
  trendPolicyTypes.value = [...(filters.policyType || [])]
  trendVisible.value = true
  loadTrend()
}

const sourceTag = { manual: 'info', task: 'success' }
const sourceText = { manual: '手动', task: '定时' }

onMounted(() => {
  load()
  loadParams()
  loadPolicyTypes()
})
</script>

<template>
  <div class="page">
    <el-card shadow="never">
      <template #header>
        <div class="card-head">
          <span>航班数据（基于系统抓取入库的数据）</span>
          <div class="btns">
            <el-button type="primary" plain @click="showTrend">
              <el-icon><TrendCharts /></el-icon>&nbsp;查看走势
            </el-button>
            <el-button type="warning" plain :loading="exporting" @click="exportAll">
              <el-icon><Document /></el-icon>&nbsp;导出记录
            </el-button>
          </div>
        </div>
      </template>

      <el-form inline class="filters">
        <el-form-item label="起飞">
          <el-input v-model="filters.dpt" placeholder="三字码" maxlength="3" clearable style="width: 100px" @keyup.enter="search" />
        </el-form-item>
        <el-form-item label="到达">
          <el-input v-model="filters.arr" placeholder="三字码" maxlength="3" clearable style="width: 100px" @keyup.enter="search" />
        </el-form-item>
        <el-form-item label="航班号">
          <el-input v-model="filters.flightNo" placeholder="模糊匹配" clearable style="width: 120px" @keyup.enter="search" />
        </el-form-item>
        <el-form-item label="政策类型">
          <el-select
            v-model="filters.policyType"
            placeholder="全部，可多选"
            clearable
            filterable
            multiple
            collapse-tags
            collapse-tags-tooltip
            style="width: 220px"
            @change="search"
          >
            <el-option v-for="t in policyTypeOptions" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源">
          <el-radio-group v-model="filters.source" @change="search">
            <el-radio-button value="">全部</el-radio-button>
            <el-radio-button value="manual">手动</el-radio-button>
            <el-radio-button value="task">定时</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="航班日期">
          <el-date-picker
            v-model="filters.flightDateRange"
            type="daterange"
            range-separator="至"
            start-placeholder="开始"
            end-placeholder="结束"
            value-format="YYYY-MM-DD"
            style="width: 240px"
            @change="search"
          />
        </el-form-item>
        <el-form-item label="抓取时间">
          <el-date-picker
            v-model="filters.crawlRange"
            type="daterange"
            range-separator="至"
            start-placeholder="开始"
            end-placeholder="结束"
            value-format="YYYY-MM-DD"
            style="width: 240px"
            @change="search"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">筛选</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>

      <el-table :data="list" v-loading="loading" size="small" border stripe>
        <el-table-column prop="createdAt" label="数据更新时间" width="150" />
        <el-table-column label="来源" width="70">
          <template #default="{ row }">
            <el-tag size="small" :type="sourceTag[row.source]">{{ sourceText[row.source] || row.source }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="flightDate" label="航班日期" width="105" />
        <el-table-column label="航线" width="100">
          <template #default="{ row }">{{ row.dpt }}→{{ row.arr }}</template>
        </el-table-column>
        <el-table-column prop="flightNo" label="航班号" width="95" />
        <el-table-column prop="mainFlightNo" label="主飞航班号" width="100" />
        <el-table-column prop="cabin" label="舱位" width="65" />
        <el-table-column prop="policyType" label="政策类型" min-width="110" show-overflow-tooltip />
        <el-table-column label="就旅伴外放退改价" width="135" align="right">
          <template #default="{ row }">{{ row.followBasePrice ?? '' }}</template>
        </el-table-column>
        <el-table-column label="全网低价" width="105" align="right">
          <template #default="{ row }">
            {{ (row.sellPrice ?? '') + (row.externalCabin ? `(${row.externalCabin})` : '') }}
          </template>
        </el-table-column>
        <el-table-column label="自有政策" width="85" align="right">
          <template #default="{ row }">{{ row.selfPrice ?? '' }}</template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="page.current"
          v-model:page-size="page.size"
          :total="total"
          :page-sizes="[20, 50, 100, 200]"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="load"
          @size-change="search"
        />
      </div>
    </el-card>

    <!-- 走势图 -->
    <el-dialog v-model="trendVisible" :title="`价格走势（${trendRoute}，按航班日期聚合最低价）`" width="860px">
      <el-form inline class="trend-filters">
        <el-form-item label="航班信息">
          <el-select
            v-model="trendParamId"
            placeholder="全部航线"
            clearable
            filterable
            style="width: 240px"
            @change="loadTrend"
          >
            <el-option v-for="p in paramList" :key="p.id" :label="`${p.name}（${paramLabel(p)}）`" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="航班号">
          <el-input
            v-model="trendFlightNo"
            placeholder="可空，模糊匹配"
            clearable
            style="width: 150px"
            @keyup.enter="loadTrend"
            @clear="loadTrend"
          />
        </el-form-item>
        <el-form-item label="政策类型">
          <el-select
            v-model="trendPolicyTypes"
            placeholder="全部（可多选看指定产品）"
            clearable
            filterable
            multiple
            collapse-tags
            collapse-tags-tooltip
            style="width: 220px"
            @change="loadTrend"
          >
            <el-option v-for="t in policyTypeOptions" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="航班日期">
          <el-date-picker
            v-model="trendDateRange"
            type="daterange"
            range-separator="至"
            start-placeholder="开始"
            end-placeholder="结束"
            value-format="YYYY-MM-DD"
            :clearable="false"
            style="width: 240px"
            @change="loadTrend"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="trendLoading" @click="loadTrend">查询走势</el-button>
        </el-form-item>
      </el-form>
      <div v-loading="trendLoading">
        <TrendChart v-if="trendData.length" :data="trendData" />
        <el-empty v-else-if="!trendLoading" description="暂无数据" />
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.btns {
  display: flex;
  gap: 10px;
}
.filters :deep(.el-form-item) {
  margin-bottom: 8px;
}
.trend-filters {
  margin-bottom: 4px;
}
.trend-filters :deep(.el-form-item) {
  margin-bottom: 8px;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
</style>
