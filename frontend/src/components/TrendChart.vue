<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps({
  /* [{ flightDate, minSellPrice, sellCabin, minSelfPrice, selfCabin, recordCount }] */
  data: { type: Array, default: () => [] },
})

const el = ref(null)
let chart = null

function fmtPrice(v, cabin) {
  if (v == null) return '-'
  return cabin ? `${v}(${cabin})` : `${v}`
}

function render() {
  if (!el.value) return
  if (!chart) chart = echarts.init(el.value)
  const dates = props.data.map((d) => d.flightDate)
  const sell = props.data.map((d) => d.minSellPrice)
  const self = props.data.map((d) => d.minSelfPrice)
  chart.setOption({
    tooltip: {
      trigger: 'axis',
      formatter(params) {
        const d = props.data[params[0].dataIndex] || {}
        const lines = [d.flightDate]
        for (const p of params) {
          if (p.value == null) continue
          const cabin = p.seriesName === '全网最低价' ? d.sellCabin : d.selfCabin
          lines.push(`${p.marker}${p.seriesName}: ${fmtPrice(p.value, cabin)}`)
        }
        if (d.recordCount != null) lines.push(`记录数: ${d.recordCount}`)
        return lines.join('<br/>')
      },
    },
    legend: { data: ['全网最低价', '自有政策最低价'], top: 4 },
    grid: { left: 50, right: 24, top: 40, bottom: 60 },
    xAxis: { type: 'category', data: dates, axisLabel: { rotate: 30 } },
    yAxis: { type: 'value', name: '价格', scale: true },
    series: [
      {
        name: '全网最低价',
        type: 'line',
        data: sell,
        connectNulls: false,
        symbolSize: 7,
        lineStyle: { width: 2.5 },
        itemStyle: { color: '#1a7f4b' },
        label: {
          show: true,
          position: 'top',
          fontSize: 11,
          formatter: (p) => (p.value == null ? '' : fmtPrice(p.value, props.data[p.dataIndex]?.sellCabin)),
        },
      },
      {
        name: '自有政策最低价',
        type: 'line',
        data: self,
        connectNulls: false,
        symbolSize: 6,
        lineStyle: { width: 2, type: 'dashed' },
        itemStyle: { color: '#e6a23c' },
      },
    ],
  })
  chart.resize()
}

function resize() {
  chart && chart.resize()
}

onMounted(() => {
  render()
  window.addEventListener('resize', resize)
})

watch(() => props.data, render, { deep: true })

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  if (chart) {
    chart.dispose()
    chart = null
  }
})
</script>

<template>
  <div ref="el" class="trend-chart"></div>
</template>

<style scoped>
.trend-chart {
  width: 100%;
  height: 420px;
}
</style>
