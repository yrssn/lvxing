import { get, post, put, del } from './request'

/* ---------- 认证 ---------- */
export const apiLogin = (username, password) => post('/api/auth/login', { username, password })

/* ---------- 用户管理（仅管理员） ---------- */
export const apiUserList = () => get('/api/users')
export const apiUserCreate = (data) => post('/api/users', data)
export const apiUserUpdate = (id, data) => put(`/api/users/${id}`, data)
export const apiUserDelete = (id) => del(`/api/users/${id}`)

/* ---------- 系统设置 ---------- */
export const apiGetCookie = () => get('/api/settings/cookie')
export const apiSaveCookie = (cookie) => put('/api/settings/cookie', { cookie })
export const apiTestCookie = () => post('/api/settings/test-cookie')

/* ---------- 手动抓取 ---------- */
export const apiScrapeRun = (params) => post('/api/scrape/run', params)

/* ---------- 抓取历史 ---------- */
export const apiHistoryList = (limit = 50) => get(`/api/history?limit=${limit}`)
export const apiHistoryRecords = (id) => get(`/api/history/${id}/records`)
export const apiHistoryDelete = (id) => del(`/api/history/${id}`)

/* ---------- 航班信息（查询参数） ---------- */
export const apiParamList = (keyword = '') => get(`/api/params?keyword=${encodeURIComponent(keyword)}`)
export const apiParamCreate = (data) => post('/api/params', data)
export const apiParamUpdate = (id, data) => put(`/api/params/${id}`, data)
export const apiParamDelete = (id) => del(`/api/params/${id}`)

/* ---------- 定时任务 ---------- */
export const apiTaskList = () => get('/api/tasks')
export const apiTaskCreate = (data) => post('/api/tasks', data)
export const apiTaskUpdate = (id, data) => put(`/api/tasks/${id}`, data)
export const apiTaskDelete = (id) => del(`/api/tasks/${id}`)
export const apiTaskToggle = (id, enabled) => post(`/api/tasks/${id}/toggle`, { enabled })
export const apiTaskRunNow = (id) => post(`/api/tasks/${id}/run-now`)
export const apiTaskLogs = (id, limit = 50) => get(`/api/tasks/${id}/logs?limit=${limit}`)

/* ---------- 航班数据 ---------- */
function buildQuery(params) {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (Array.isArray(v)) {
      for (const item of v) {
        if (item !== '' && item !== null && item !== undefined) qs.append(k, item)
      }
    } else if (v !== '' && v !== null && v !== undefined) {
      qs.set(k, v)
    }
  }
  const s = qs.toString()
  return s ? `?${s}` : ''
}

export const apiDataRecords = (filters) => get(`/api/data/records${buildQuery(filters)}`)
export const apiDataTrend = (filters) => get(`/api/data/trend${buildQuery(filters)}`)
export const apiDataPolicyTypes = () => get('/api/data/policy-types')
